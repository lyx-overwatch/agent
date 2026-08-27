"""Storage diagnostic service — direct OBS/S3 verification without the agent loop.

These operations bypass the sandbox / agent entirely so object-storage
connectivity, upload, listing, and delete can be validated quickly after a
deployment, without waiting for the (slow) sandbox container to spin up.

All operations return a JSON dict and swallow exceptions into an
``{"ok": False, "error": ...}`` payload (rather than a 500) so the underlying
boto3 / OBS error is visible directly in the curl response.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loguru import logger

from app.core.config import settings
from app.core.storage import get_storage


def _error_response(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class StorageService:
    """Direct storage operations for post-deploy OBS/MinIO checks."""

    @staticmethod
    async def health() -> dict[str, Any]:
        """Test connection, credentials, and bucket existence."""
        storage = get_storage()
        try:
            return await storage.test_connection()
        except Exception as exc:  # noqa: BLE001 — surface the error in the response
            logger.exception("Storage connection test failed")
            return _error_response(exc)

    @staticmethod
    async def upload(*, content: str, name: str, prefix: str = "test") -> dict[str, Any]:
        """Upload a small test file and return its key + download URL."""
        storage = get_storage()
        key = f"{prefix.rstrip('/')}/{name}" if prefix else name
        content_bytes = content.encode("utf-8")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(content_bytes)
            tmp_path = Path(tmp.name)

        try:
            uploaded_key = await storage.upload(local_path=tmp_path, key=key)
            url = await storage.download_url(uploaded_key)
        except Exception as exc:  # noqa: BLE001 — return the error inline
            logger.exception("Storage upload test failed for key {}", key)
            return {**_error_response(exc), "key": key}
        finally:
            tmp_path.unlink(missing_ok=True)

        return {
            "ok": True,
            "key": uploaded_key,
            "download_url": url,
            "size": len(content_bytes),
        }

    @staticmethod
    async def download_url(*, key: str, expires_in: int = 3600, download: bool = False) -> dict[str, Any]:
        """Generate a download URL for an existing key without uploading.

        This validates the OBS proxy download chain (V2 pre-signed URL) in
        isolation — no sandbox, no agent, no upload.  Point ``key`` at an
        object that already exists (e.g. one returned by :meth:`upload`) and
        navigate the returned URL to confirm the proxy forwards correctly.
        """
        storage = get_storage()
        is_s3 = settings.storage_backend == "s3"

        disposition = ""
        if download and is_s3:
            safe_name = key.rsplit("/", 1)[-1]
            try:
                safe_name.encode("ascii")
            except UnicodeEncodeError:
                safe_name = f"UTF-8''{quote(safe_name)}"
            disposition = f'attachment; filename="{safe_name}"'

        try:
            if is_s3:
                url = await storage.download_url(key, expires_in=expires_in, response_content_disposition=disposition)
            else:
                url = await storage.download_url(key, expires_in=expires_in)
        except Exception as exc:  # noqa: BLE001 — return the error inline
            logger.exception("Storage download URL generation failed for key {}", key)
            return {**_error_response(exc), "key": key}

        return {
            "ok": True,
            "key": key,
            "download_url": url,
            "backend": settings.storage_backend,
            "expires_in": expires_in,
            "disposition": disposition or "inline",
        }

    @staticmethod
    async def list_objects(*, prefix: str = "") -> dict[str, Any]:
        """List objects under a key prefix."""
        storage = get_storage()
        try:
            objects = await storage.list_objects(prefix)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Storage list test failed for prefix {}", prefix)
            return {**_error_response(exc), "prefix": prefix}
        return {"ok": True, "prefix": prefix, "count": len(objects), "objects": objects}

    @staticmethod
    async def delete(*, key: str) -> dict[str, Any]:
        """Delete a single object by key and verify it is gone."""
        storage = get_storage()
        try:
            await storage.delete(key)
            exists_after = await storage.exists(key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Storage delete test failed for key {}", key)
            return {**_error_response(exc), "key": key}
        return {
            "ok": True,
            "key": key,
            "deleted": not exists_after,
            "exists_after": exists_after,
        }
