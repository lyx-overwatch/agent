"""Storage backend abstraction — pluggable file storage for SkillHub.

Provides a protocol-based storage layer with two implementations:

- :class:`LocalStorageBackend`: files stored on local disk; download URL
  points to the SkillHub file-serving API (suitable for development and
  non-containerised deployments).
- :class:`S3StorageBackend`: files stored in any S3-compatible object
  storage (Huawei Cloud OBS, MinIO, AWS S3, etc.); ``download_url``
  returns a pre-signed URL (used by the diagnostic upload endpoint), but
  the file-serving route proxies the object through SkillHub instead —
  OBS's endpoint is internal and not CORS-enabled, so the browser cannot
  fetch the pre-signed URL directly.

Select the backend via ``STORAGE_BACKEND`` env var (``"local"`` or ``"s3"``).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import mimetypes
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from loguru import logger

# ── S3 upload retry policy ───────────────────────────────────────────────────

_S3_RETRY_ATTEMPTS = 3
_S3_RETRY_BASE_DELAY = 1.0  # seconds, exponential backoff: 1s, 2s, ...


def _is_retryable_upload_error(exc: Exception) -> bool:
    """Return ``True`` for transient S3 errors worth retrying.

    Retries network failures, throttling, and 5xx server errors.  Client
    errors (4xx: ``NoSuchBucket``, ``AccessDenied``, ``SignatureDoesNotMatch``,
    …) are *not* retried — retrying them wastes a request and cannot succeed.
    """
    try:
        import botocore.exceptions as boto_exc
    except ImportError:  # pragma: no cover — botocore ships with boto3
        return isinstance(exc, (ConnectionError, TimeoutError))

    if isinstance(
        exc,
        (
            boto_exc.ConnectionError,
            boto_exc.EndpointConnectionError,
            boto_exc.ConnectTimeoutError,
            boto_exc.ReadTimeoutError,
            boto_exc.ConnectionClosedError,
        ),
    ):
        return True
    if isinstance(exc, boto_exc.ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code", "")
        if isinstance(status, int) and status >= 500:
            return True
        if code in ("RequestTimeout", "SlowDown", "Throttling", "InternalError", "ServiceUnavailable"):
            return True
    return False


# ── StorageBackend protocol ──────────────────────────────────────────────────


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for pluggable file storage backends.

    Implementations must be **stateless** or safely singleton-cached —
    the factory (:func:`get_storage`) may return the same instance for
    every call.
    """

    async def upload(self, *, local_path: Path, key: str, content_type: str | None = None) -> str:
        """Upload a local file to storage.

        Args:
            local_path: Path on local disk to the file to upload.
            key: Object key (path) in the storage bucket, e.g.
                ``"users/123/threads/tid/outputs/report.pdf"``.
            content_type: MIME type hint. Guessed from the file extension
                when omitted.

        Returns:
            The **storage key** on success (same as *key* for most
            implementations).
        """
        ...

    async def test_connection(self) -> dict[str, Any]:
        """Verify connectivity and credentials against the storage backend.

        Raises on failure; returns a small diagnostic dict on success
        (backend type, endpoint/bucket info, and round-trip latency where
        applicable).  Used by the ``/storage/health`` diagnostic endpoint.
        """
        ...

    async def download_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Generate a time-limited download URL for *key*.

        Args:
            key: Object key in the storage bucket.
            expires_in: URL validity period in seconds (default 1 hour).

        Returns:
            A fully qualified URL the client can GET to download the
            file. For the local backend this is a SkillHub API path;
            for S3 this is a pre-signed URL.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete a file from storage. Idempotent."""
        ...

    async def exists(self, key: str) -> bool:
        """Check whether a file exists in storage."""
        ...

    async def get_metadata(self, key: str) -> dict[str, Any]:
        """Return file metadata.

        Returns a dict with keys: ``size`` (int, bytes), ``content_type``
        (str), ``last_modified`` (float, epoch seconds).
        """
        ...

    async def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        """List objects under a key prefix.

        Returns a list of dicts, each with keys: ``key`` (str),
        ``size`` (int), ``last_modified`` (float, epoch seconds).
        Folders / common prefixes are represented as entries with
        ``key`` ending in ``"/"`` and ``size`` set to 0.
        """
        ...

    async def download_bytes(self, key: str) -> bytes:
        """Download file content as raw bytes.

        Args:
            key: Object key in the storage bucket.

        Returns:
            Raw file content bytes.
        """
        ...

    async def download_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Yield file content in chunks without buffering the whole object.

        Prefer this over :meth:`download_bytes` when streaming a file back to
        a client — it avoids holding the entire object in memory.
        """
        ...

    async def delete_prefix(self, prefix: str) -> int:
        """Recursively delete ALL objects under *prefix*.

        This is a deep delete — it removes every object whose key
        starts with *prefix*, regardless of nesting depth.  Folders
        (common prefixes) have no on-disk representation in S3 and
        are implicitly cleaned up when their contents are deleted.

        Returns the number of objects deleted.

        ``KeyError`` → there were no objects under *prefix* (caught
        by implementations and treated as success).
        """
        ...


# ── Local (filesystem) backend ──────────────────────────────────────────────


class LocalStorageBackend:
    """Storage backend that keeps files on the local filesystem.

    ``download_url`` returns a relative API path that the SkillHub file-
    serving route resolves back to this backend's on-disk location. This
    keeps the local-dev experience simple (no extra services needed).

    Parameters
    ----------
    base_dir: Root directory for stored files. Thread-specific
        subdirectories are created underneath.
    serve_prefix: URL prefix for the SkillHub file-serving endpoint,
        e.g. ``"/py/api/chat/files/"``.
    """

    def __init__(self, base_dir: Path | str, serve_prefix: str = "/py/api/chat/files/") -> None:
        self._base_dir = Path(base_dir).resolve()
        self._serve_prefix = serve_prefix.rstrip("/") + "/"

    # ── helpers ─────────────────────────────────────────────────────────

    def _physical_path(self, key: str) -> Path:
        p = (self._base_dir / key).resolve()
        # Safety: ensure resolved path stays under base_dir
        if not str(p).startswith(str(self._base_dir)):
            raise ValueError(f"Key {key!r} escapes base directory")
        return p

    # ── StorageBackend ───────────────────────────────────────────────────

    async def upload(self, *, local_path: Path, key: str, content_type: str | None = None) -> str:
        dest = self._physical_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(local_path.read_bytes())
        logger.info("LocalStorage: uploaded {} → {}", local_path.name, dest)
        return key

    async def test_connection(self) -> dict[str, Any]:
        return {
            "backend": "local",
            "ok": True,
            "base_dir": str(self._base_dir),
        }

    async def download_url(self, key: str, *, expires_in: int = 3600) -> str:
        # Local storage: return the SkillHub file-serving API path.
        # The serve_prefix has format "/py/api/chat/files/" and the route
        # expects a conversation_id as a path segment, but here we just
        # return a relative path that the frontend resolves against the
        # API base.  The actual routing is:
        #   GET /py/api/chat/files/{conversation_id}?path=/mnt/user-data/...
        # So for local storage, the caller (route handler) must construct
        # the full URL using conversation_id and virtual path.
        return key

    async def download_bytes(self, key: str) -> bytes:
        return self._physical_path(key).read_bytes()

    async def download_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        p = self._physical_path(key)
        with p.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def delete(self, key: str) -> None:
        p = self._physical_path(key)
        try:
            p.unlink()
            logger.debug("LocalStorage: deleted {}", key)
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        return self._physical_path(key).is_file()

    async def get_metadata(self, key: str) -> dict[str, Any]:
        p = self._physical_path(key)
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {key}")
        stat = p.stat()
        content_type, _ = mimetypes.guess_type(str(p))
        return {
            "size": stat.st_size,
            "content_type": content_type or "application/octet-stream",
            "last_modified": stat.st_mtime,
        }

    async def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        base = self._physical_path(prefix.rstrip("/"))
        if not base.exists():
            return []
        results: list[dict[str, Any]] = []
        for entry in sorted(base.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            rel = str(entry.relative_to(self._base_dir)).replace("\\", "/")
            if entry.is_dir():
                results.append({"key": rel + "/", "size": 0, "last_modified": entry.stat().st_mtime})
            else:
                results.append({"key": rel, "size": entry.stat().st_size, "last_modified": entry.stat().st_mtime})
        return results

    async def delete_prefix(self, prefix: str) -> int:
        """Recursively delete the directory tree identified by *prefix*."""
        import shutil

        base = self._physical_path(prefix.rstrip("/"))
        if not base.exists():
            return 0
        # Count files before deletion
        count = sum(1 for _ in base.rglob("*") if _.is_file())
        shutil.rmtree(base)
        logger.info("LocalStorage: deleted prefix {} ({} file(s))", prefix, count)
        return count

# ── S3-compatible backend (OBS / MinIO / AWS S3) ─────────────────────────────


class S3StorageBackend:
    """Storage backend for any S3-compatible object storage.

    Tested with: Huawei Cloud OBS, MinIO, AWS S3.

    Parameters
    ----------
    endpoint: S3 endpoint URL (e.g. ``https://obs.cn-south-1.myhuaweicloud.com``
        or ``http://localhost:9000`` for MinIO).
    access_key: S3 access key / AK.
    secret_key: S3 secret key / SK.
    bucket: Bucket name.
    region: Region name (e.g. ``"cn-south-1"``).
    """

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "",
        addressing_style: str = "virtual",
        proxy_url: str = "",
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._addressing_style = addressing_style
        self._proxy_url = proxy_url.rstrip("/") if proxy_url else ""
        self._client: Any = None  # Lazy-init boto3 client
        self._auto_create_bucket: bool = False  # Set by factory
        self._client_lock = threading.Lock()  # Guards lazy client init

    def _build_boto_config(self):
        """Build the botocore ``Config`` for Huawei OBS compatibility.

        OBS's S3 compatibility is incomplete: its SigV4 verification only
        accepts ``UNSIGNED-PAYLOAD`` and ``STREAMING-AWS4-HMAC-SHA256-PAYLOAD``
        as the payload mode.  boto3's default is to sign the payload with the
        real SHA-256 hex, which OBS rejects on ``put_object`` with
        ``XAmzContentSHA256Mismatch``.  We therefore:

        * disable payload signing (``payload_signing_enabled=False``) so boto3
          sends ``UNSIGNED-PAYLOAD`` instead of a real hash;
        * disable the AWS request/response checksums (CRC32) that boto3 >= 1.36
          adds by default and OBS also doesn't understand.

        The checksum knobs only exist on botocore >= 1.36, so we fall back to
        the minimal config on older versions.
        """
        from botocore.config import Config as BotoConfig

        base = {
            "signature_version": "s3v4",
            "s3": {
                "addressing_style": self._addressing_style,
                "payload_signing_enabled": False,
            },
        }
        try:
            return BotoConfig(
                request_checksum_calculation="WHEN_REQUIRED",
                response_checksum_validation="WHEN_REQUIRED",
                **base,
            )
        except TypeError:  # botocore < 1.36 — checksum knobs not available
            return BotoConfig(**base)

    def _get_client(self):
        """Lazy-init the boto3 S3 client and optionally ensure the bucket exists.

        The client is created under a lock so concurrent uploads (now dispatched
        to worker threads) don't race to build multiple clients or fire
        duplicate ``head_bucket`` / ``create_bucket`` calls.
        """
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                import boto3
            except ImportError:
                raise ImportError(
                    "boto3 is required for S3 storage. Install it with: uv add boto3"
                )

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                config=self._build_boto_config(),
            )
            # Auto-create bucket on first use
            if self._auto_create_bucket:
                try:
                    self._client.head_bucket(Bucket=self._bucket)
                except Exception:
                    logger.info("S3Storage: auto-creating bucket {}", self._bucket)
                    self._client.create_bucket(Bucket=self._bucket)
            return self._client

    # ── StorageBackend ───────────────────────────────────────────────────

    def _upload_blocking(self, local_path: Path, key: str, content_type: str) -> None:
        """Blocking boto3 upload — must run in a worker thread, not the loop.

        Reads the file into memory and calls ``put_object`` with ``bytes``
        (a plain single-part PUT).  The OBS-compatible signing is configured on
        the client via :meth:`_build_boto_config` — that's what avoids OBS's
        ``XAmzContentSHA256Mismatch``.
        """
        client = self._get_client()
        data = local_path.read_bytes()
        client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def upload(self, *, local_path: Path, key: str, content_type: str | None = None) -> str:
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(local_path))
            if content_type is None:
                content_type = "application/octet-stream"

        last_exc: Exception | None = None
        attempts_made = 0
        for attempt in range(1, _S3_RETRY_ATTEMPTS + 1):
            attempts_made = attempt
            try:
                # boto3's transfer manager is synchronous — offload to a thread
                # so it never blocks the FastAPI event loop.
                await asyncio.to_thread(self._upload_blocking, local_path, key, content_type)
                logger.info("S3Storage: uploaded {} → {}/{}", local_path.name, self._bucket, key)
                return key
            except Exception as exc:  # noqa: BLE001 — retry transient, re-raise otherwise
                last_exc = exc
                retryable = _is_retryable_upload_error(exc)
                if attempt >= _S3_RETRY_ATTEMPTS or not retryable:
                    break
                delay = _S3_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "S3Storage: upload {} failed (attempt {}/{}): {} — retrying in {:.1f}s",
                    key, attempt, _S3_RETRY_ATTEMPTS, exc, delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "S3Storage: upload {} failed after {} attempt(s): {}",
            key, attempts_made, last_exc,
        )
        raise last_exc

    async def test_connection(self) -> dict[str, Any]:
        """Verify endpoint reachability, credentials, and bucket existence.

        Uses ``head_bucket`` (requires ``s3:ListBucket``) — the standard
        connectivity + auth + bucket-exists probe.  Runs the blocking call in
        a worker thread so it never stalls the event loop.
        """
        start = time.perf_counter()

        def _check() -> None:
            self._get_client().head_bucket(Bucket=self._bucket)

        await asyncio.to_thread(_check)
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        return {
            "backend": "s3",
            "ok": True,
            "endpoint": self._endpoint,
            "bucket": self._bucket,
            "region": self._region,
            "addressing_style": self._addressing_style,
            "latency_ms": latency_ms,
        }

    async def download_url(self, key: str, *, expires_in: int = 3600, response_content_disposition: str = "") -> str:
        # When a reverse-proxy prefix is configured, emit a Huawei OBS V2
        # temporary URL.  boto3's SigV4 presigned URL binds the signature to
        # the OBS host (via ``X-Amz-SignedHeaders=host``), so it cannot be
        # served through the proxy domain — the proxy rewrites the host and
        # OBS rejects the signature.  OBS's V2 signature only signs the
        # canonicalized resource + expiry, so the same URL works on any host
        # that routes to the bucket (this is what the Java backend uses).
        if self._proxy_url:
            return self._obs_v2_presigned_url(key, expires_in, response_content_disposition)

        client = self._get_client()
        params = {"Bucket": self._bucket, "Key": key}
        if response_content_disposition:
            params["ResponseContentDisposition"] = response_content_disposition
        url = client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return url

    def _obs_v2_presigned_url(self, key: str, expires_in: int, response_content_disposition: str = "") -> str:
        """Build a Huawei OBS V2 temporary URL prefixed with the proxy domain.

        V2 signature: ``Base64(HMAC-SHA1(SK, StringToSign))`` where
        ``StringToSign = "GET\\n\\n\\n{expires}\\n/{bucket}/{object}"``.
        The signature is host-independent, so it survives rewriting the host
        from the OBS endpoint to the reverse proxy.
        """
        expires = int(time.time()) + expires_in
        # CanonicalizedResource = /{bucket}/{object}.  Object keys may contain
        # non-ASCII characters (e.g. Chinese filenames), and OBS computes the
        # V2 signature over the URL-encoded key exactly as it appears in the
        # request path — so the string-to-sign and the emitted URL MUST use
        # the same percent-encoding, otherwise OBS rejects the request with
        # SignatureDoesNotMatch.
        encoded_key = quote(key, safe="/")
        string_to_sign = f"GET\n\n\n{expires}\n/{self._bucket}/{encoded_key}"
        signature = base64.b64encode(
            hmac.new(
                self._secret_key.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        query = (
            f"AccessKeyId={quote(self._access_key, safe='')}"
            f"&Expires={expires}"
            f"&Signature={quote(signature, safe='')}"
        )
        if response_content_disposition:
            query += f"&response-content-disposition={quote(response_content_disposition, safe='')}"

        return f"{self._proxy_url}/{encoded_key}?{query}"

    async def download_bytes(self, key: str) -> bytes:
        client = self._get_client()
        resp = client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    async def download_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        client = self._get_client()
        resp = await asyncio.to_thread(client.get_object, Bucket=self._bucket, Key=key)
        body = resp["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    async def delete(self, key: str) -> None:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self._bucket, Key=key)
            logger.debug("S3Storage: deleted {}", key)
        except Exception:
            pass

    async def exists(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    async def get_metadata(self, key: str) -> dict[str, Any]:
        client = self._get_client()
        try:
            resp = client.head_object(Bucket=self._bucket, Key=key)
            return {
                "size": resp.get("ContentLength", 0),
                "content_type": resp.get("ContentType", "application/octet-stream"),
                "last_modified": resp["LastModified"].timestamp(),
            }
        except Exception:
            raise FileNotFoundError(f"File not found in S3: {key}")

    async def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        client = self._get_client()
        prefix = prefix.rstrip("/") + "/" if prefix else ""
        results: list[dict[str, Any]] = []

        # Flat recursive listing (no Delimiter): return every object under
        # the prefix so callers can rebuild a full nested tree.  Using a
        # ``Delimiter="/"`` here rolls subdirectories up into CommonPrefixes
        # and hides files nested more than one level deep (e.g.
        # ``outputs/tesla-website/index.html`` would only surface as an empty
        # ``tesla-website/`` directory marker).
        paginator = client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    obj_key = obj["Key"]
                    if obj_key == prefix:
                        continue
                    results.append(
                        {
                            "key": obj_key,
                            "size": obj.get("Size", 0),
                            "last_modified": obj["LastModified"].timestamp(),
                        }
                    )
        except Exception as exc:
            logger.warning("S3Storage: list_objects failed for prefix {}: {}", prefix, exc)

        results.sort(key=lambda x: x["key"].lower())
        return results

    async def delete_prefix(self, prefix: str) -> int:
        """Recursively delete ALL objects under *prefix*.

        Uses flat listing (no ``Delimiter``) so nested objects are
        found regardless of depth, then batch-deletes in groups of
        up to 1000 (the S3 ``DeleteObjects`` limit).
        """
        client = self._get_client()
        deleted = 0
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                objects = page.get("Contents", [])
                if not objects:
                    continue
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": delete_keys},
                )
                deleted += len(delete_keys)
        except Exception as exc:
            logger.warning("S3Storage: delete_prefix failed for {}: {}", prefix, exc)
        if deleted:
            logger.info("S3Storage: deleted prefix {} ({} object(s))", prefix, deleted)
        return deleted


# ── Factory ──────────────────────────────────────────────────────────────────


_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured :class:`StorageBackend` singleton.

    Reads ``STORAGE_BACKEND`` from the environment / Pydantic settings:
    - ``"local"`` → :class:`LocalStorageBackend` (default for development)
    - ``"s3"``    → :class:`S3StorageBackend` (OBS / MinIO / AWS S3)
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from app.core.config import settings

    backend_type = settings.storage_backend
    logger.info("Initialising storage backend: {}", backend_type)

    if backend_type == "s3":
        _storage_instance = S3StorageBackend(
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            addressing_style=settings.s3_addressing_style,
            proxy_url=settings.s3_proxy_url,
        )
        # Ensure bucket exists on first use (deferred — actual check
        # happens on first api call to avoid blocking startup).
        _storage_instance._auto_create_bucket = True
    else:
        # local — default for development
        from app.core.config_loader import get_agent_config

        cfg = get_agent_config()
        base_dir = cfg.path_provider.get_base_dir() if cfg and cfg.path_provider else Path("./.agent-sdk").resolve()
        _storage_instance = LocalStorageBackend(base_dir=base_dir)

    return _storage_instance
