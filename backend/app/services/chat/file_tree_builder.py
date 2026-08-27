"""File tree builder — construct virtual file trees and resolve sandbox paths.

Provides file-tree construction for the frontend (outputs / workspace / uploads),
virtual-to-physical path resolution, file metadata, and workspace sanitization.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config_loader import get_agent_config
from app.core.storage import LocalStorageBackend, StorageBackend, get_storage
from app.utils import PREVIEWABLE_EXTENSIONS

# ── Virtual path prefixes ────────────────────────────────────────────────
_SANDBOX_PREFIX = "/mnt/user-data/"
_AGENT_PREFIX = "/agent-data/"


class FileTreeBuilder:
    """Build virtual file trees and resolve sandbox file paths."""

    def __init__(self) -> None:
        self._storage: StorageBackend | None = None

    @property
    def storage(self) -> StorageBackend:
        """Lazy-init the storage backend singleton."""
        if self._storage is None:
            self._storage = get_storage()
        return self._storage

    @staticmethod
    def _is_pure_storage_mode() -> bool:
        """Return ``True`` when the file tree should be built from storage only.

        Pure-storage mode applies when the sandbox runs in a remote K8s Pod
        (via the provisioner) and files are synced to object storage after
        the agent run.  In this mode the backend Pod has **no** direct
        filesystem access to the sandbox Pod's files, so local disk
        scanning would only produce empty results.

        Detection: the sandbox provider is an AioSandboxProvider configured
        with a non-empty ``provisioner_url``.
        """
        from app.core.storage import LocalStorageBackend, get_storage

        if isinstance(get_storage(), LocalStorageBackend):
            return False
        cfg = get_agent_config()
        provider = cfg.sandbox_provider if cfg else None
        if provider is None:
            return False
        try:
            return bool((provider._config or {}).get("provisioner_url"))
        except Exception:
            return False

    # ── File tree ────────────────────────────────────────────────────────────

    async def build_file_tree(self, conversation_id: str, thread_id: str, user_id: int) -> dict[str, Any]:
        """Build a recursive file tree for outputs, workspace, and uploads.

        Returns a dict with ``conversation_id`` and ``roots`` — three root
        nodes (outputs, workspace, uploads) each containing a recursive tree
        of files and directories.  Empty directories are omitted.

        When using an S3-compatible storage backend, files that have already
        been uploaded to object storage are included alongside local files.

        In **pure-storage mode** (K8s provisioner + remote sandbox), local
        disk scanning is skipped entirely — all entries come from the
        storage backend because the sandbox Pod's filesystem is not
        accessible from the backend.
        """
        cfg = get_agent_config()
        pp = cfg.path_provider
        vp = pp.get_virtual_prefix()

        pure_storage = self._is_pure_storage_mode()

        roots: list[dict[str, Any]] = []
        for bucket_name, bucket_label, get_dir_fn in [
            ("outputs", "产物", pp.get_outputs_dir),
            ("workspace", "工作区", pp.get_workspace_dir),
            ("uploads", "上传文件", pp.get_uploads_dir),
        ]:
            if pure_storage:
                # Pure-storage mode — K8s sandbox files are NOT on local
                # disk; everything lives in the storage backend.
                children = await self._scan_storage(
                    vp,
                    bucket_name,
                    thread_id=thread_id,
                    user_id=str(user_id),
                )
            else:
                physical_dir = get_dir_fn(thread_id, user_id=str(user_id))
                # Collect entries from local filesystem
                children = self._scan_dir(physical_dir, vp, bucket_name) if physical_dir.exists() else []

                # If using remote storage (Docker + MinIO / S3), merge in
                # storage-backed entries so files that were synced after
                # the agent run are visible.
                if not isinstance(self.storage, LocalStorageBackend):
                    remote_children = await self._scan_storage(vp, bucket_name, thread_id=thread_id, user_id=str(user_id))
                    children = self._merge_tree_entries(children, remote_children)

            roots.append(
                {
                    "name": bucket_name,
                    "label": bucket_label,
                    "type": "directory",
                    "virtual_path": f"{vp}/{bucket_name}/",
                    "children": children,
                }
            )

        return {"conversation_id": conversation_id, "roots": roots}

    def _scan_dir(self, physical_dir: Path, virtual_prefix: str, bucket_name: str, *, _base_dir: Path | None = None) -> list[dict[str, Any]]:
        """Recursively scan a physical directory and return a sorted tree node list.

        Directories come first, then files; both sorted alphabetically (case-insensitive).

        Args:
            physical_dir: The directory currently being scanned.
            virtual_prefix: Virtual path prefix (e.g. ``/agent-data``).
            bucket_name: Bucket name for virtual path construction (e.g. ``workspace``).
            _base_dir: Internal — the root directory of the current bucket, used to
                compute correct relative paths across recursion levels.
        """
        if _base_dir is None:
            _base_dir = physical_dir

        nodes: list[dict[str, Any]] = []
        entries = sorted(physical_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))

        for entry in entries:
            # Skip skill-injection artifacts — internal runtime files
            # injected by read_skill, not user-generated content.
            if entry.name == ".skills":
                continue
            relative = entry.relative_to(_base_dir)
            rel_str = str(relative).replace("\\", "/")
            virtual_path = f"{virtual_prefix}/{bucket_name}/{rel_str}"

            if entry.is_dir():
                children = self._scan_dir(entry, virtual_prefix, bucket_name, _base_dir=_base_dir)
                nodes.append(
                    {
                        "name": entry.name,
                        "type": "directory",
                        "virtual_path": virtual_path,
                        "children": children,
                        "size": None,
                        "extension": None,
                        "content_type": None,
                        "previewable": False,
                    }
                )
            else:
                stat = entry.stat()
                ext = entry.suffix.lower()
                media_type, _ = mimetypes.guess_type(str(entry))
                nodes.append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "virtual_path": virtual_path,
                        "children": None,
                        "size": stat.st_size,
                        "extension": ext,
                        "content_type": media_type or "application/octet-stream",
                        "previewable": ext in PREVIEWABLE_EXTENSIONS,
                    }
                )

        return nodes

    # ── Storage-backed file tree merging ──────────────────────────────────────

    async def _scan_storage(self, virtual_prefix: str, bucket_name: str, *, thread_id: str, user_id: str) -> list[dict[str, Any]]:
        """List files from the storage backend for a given bucket.

        Translates storage keys back into virtual file-tree entries with
        the same shape as :meth:`_scan_dir`.

        ``list_objects`` is async — await it directly rather than wrapping
        it in ``asyncio.run`` + ``ThreadPoolExecutor().result(timeout=30)``,
        which previously blocked the event loop for up to 30 s per bucket
        (and thus starved the ``/health`` liveness probe into a SIGKILL).
        """
        # Build the storage key prefix: users/{uid}/threads/{tid}/{bucket}/
        storage_prefix = f"users/{user_id}/threads/{thread_id}/{bucket_name}/"
        try:
            objects = await self.storage.list_objects(storage_prefix)
        except Exception as exc:
            logger.warning("FileTreeBuilder: storage list_objects failed for {}/{}: {}", bucket_name, thread_id, exc)
            return []

        return self._storage_objects_to_tree(objects, storage_prefix, virtual_prefix, bucket_name)

    @staticmethod
    def _storage_objects_to_tree(
        objects: list[dict[str, Any]],
        storage_prefix: str,
        virtual_prefix: str,
        bucket_name: str,
    ) -> list[dict[str, Any]]:
        """Convert flat storage object list into a nested tree structure."""
        # Build tree nodes keyed by relative path
        tree: dict[str, dict[str, Any]] = {}
        for obj in objects:
            full_key: str = obj["key"]
            # Strip the storage prefix to get the relative path
            rel = full_key.removeprefix(storage_prefix)
            if not rel:
                continue

            # Skip skill-injection artifacts — internal runtime files
            # injected by read_skill, not user-generated content.
            if ".skills" in rel.split("/"):
                continue

            # Determine if it's a directory marker
            is_dir = rel.endswith("/")
            if is_dir:
                rel = rel.rstrip("/")

            parts = rel.split("/")
            current_path = ""
            for i, part in enumerate(parts):
                parent_path = current_path
                current_path = f"{current_path}/{part}" if current_path else part
                if current_path in tree:
                    continue

                is_leaf_dir = is_dir and i == len(parts) - 1
                ext = "" if is_dir else Path(part).suffix.lower()
                media_type = None if is_dir else (mimetypes.guess_type(part)[0] or "application/octet-stream")

                node: dict[str, Any] = {
                    "name": part,
                    "type": "directory" if is_leaf_dir or i < len(parts) - 1 else "file",
                    "virtual_path": f"{virtual_prefix}/{bucket_name}/{current_path}",
                    "children": [],
                    "size": 0 if is_dir else obj.get("size"),
                    "extension": ext,
                    "content_type": media_type,
                    "previewable": ext in PREVIEWABLE_EXTENSIONS if ext else False,
                }
                tree[current_path] = node
                if parent_path and parent_path in tree:
                    parent = tree[parent_path]
                    # Avoid duplicates
                    if not any(c["name"] == part for c in parent.get("children", [])):
                        parent.setdefault("children", []).append(node)

        # Return top-level entries
        top_level = [n for p, n in tree.items() if "/" not in p]
        top_level.sort(key=lambda n: (not n["type"] == "directory", n["name"].lower()))
        return top_level

    @staticmethod
    def _merge_tree_entries(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge remote entries into local entries, deduplicating by name.

        Local entries take precedence; remote entries fill in what's missing.
        """
        local_names = {entry["name"] for entry in local}
        merged = list(local)
        for entry in remote:
            if entry["name"] not in local_names:
                merged.append(entry)
        merged.sort(key=lambda n: (not n["type"] == "directory", n["name"].lower()))
        return merged

    # ── Workspace sanitization ───────────────────────────────────────────────

    def sanitize_workspace(self, thread_id: str, user_id: str) -> None:
        """Clean up known garbage artifacts left by shell command misinterpretation.

        Windows / non-bash shells may interpret POSIX flags as literal directory
        names (e.g. ``mkdir -p dir/`` creates a ``-p`` directory).  This method
        scans the workspace and removes such artifacts.

        Currently handled patterns:
            - Empty directories named ``-p`` (mkdir flag misinterpretation)

        Only empty / obviously-garbage entries are removed — never files with content.
        """
        cfg = get_agent_config()
        pp = cfg.path_provider
        workspace = pp.get_workspace_dir(thread_id, user_id=user_id)

        if not workspace.exists():
            return

        # ── Empty "-p" directories ──────────────────────────────────────
        _p_dir = workspace / "-p"
        try:
            if _p_dir.is_dir():
                # Only remove if empty — safety check
                if not any(_p_dir.iterdir()):
                    _p_dir.rmdir()
                    logger.info("Removed empty '-p' dir from workspace: {}", _p_dir)
        except OSError:
            pass

    # ── File resolution ───────────────────────────────────────────────────

    def resolve_file_path(self, virtual_path: str, thread_id: str, *, user_id: str | None = None) -> Path:
        """Resolve a virtual sandbox path to a physical filesystem path.

        Raises ``ValueError`` on invalid paths.
        """
        if ".." in virtual_path:
            raise ValueError("Path traversal not allowed")

        cfg = get_agent_config()
        path_provider = cfg.path_provider

        for prefix, get_dir_fn in [
            (_SANDBOX_PREFIX + "outputs/", path_provider.get_outputs_dir),
            (_SANDBOX_PREFIX + "uploads/", path_provider.get_uploads_dir),
            (_SANDBOX_PREFIX + "workspace/", path_provider.get_workspace_dir),
            (_AGENT_PREFIX + "outputs/", path_provider.get_outputs_dir),
            (_AGENT_PREFIX + "uploads/", path_provider.get_uploads_dir),
            (_AGENT_PREFIX + "workspace/", path_provider.get_workspace_dir),
        ]:
            if virtual_path.startswith(prefix):
                filename = virtual_path[len(prefix) :]
                if filename.startswith("/") or ".." in filename:
                    raise ValueError(f"Invalid file path: {virtual_path!r}")
                # 空 filename 表示目录根（如 /mnt/user-data/outputs/）——返回桶目录本身，
                # 供「打包下载整个目录」使用；文件类调用方随后会因 is_file() 判断而 404。
                target = get_dir_fn(thread_id, user_id=user_id)
                return target / filename if filename else target

        raise ValueError(f"Unsupported virtual path prefix: {virtual_path!r}")

    def get_file_info(self, virtual_path: str, thread_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        """Return file metadata (size, MIME type, previewable flag)."""
        physical = self.resolve_file_path(virtual_path, thread_id, user_id=user_id)

        if not physical.exists() or not physical.is_file():
            raise FileNotFoundError(f"File not found: {physical.name}")

        stat = physical.stat()
        ext = physical.suffix.lower()
        media_type, _ = mimetypes.guess_type(str(physical))

        return {
            "filename": physical.name,
            "size": stat.st_size,
            "content_type": media_type or "application/octet-stream",
            "extension": ext,
            "previewable": ext in PREVIEWABLE_EXTENSIONS,
        }
