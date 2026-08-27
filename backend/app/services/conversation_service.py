"""Conversation service — create, list, delete conversations and manage files."""

import hashlib
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config_loader import get_agent_config
from app.core.state_logger import delete_conversation_logs
from app.models.database import SessionLocal
from app.repositories.message_repo import MessageRepo
from app.repositories.run_repo import RunRepo
from app.utils import make_thread_id


class ConversationService:
    """Manage conversation lifecycle (create, list, delete) and file uploads."""

    def __init__(self) -> None:
        self._run_repo = RunRepo()
        self._message_repo = MessageRepo()

    # ── Create ────────────────────────────────────────────────────────────

    async def create_conversation(
        self,
        user_id: str,
        file_data: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        """Create a new conversation record and optionally upload files.

        Returns the ``conversation_id``, ``thread_id``, and uploaded file metadata.
        """
        import uuid

        conversation_id = str(uuid.uuid4())
        thread_id = make_thread_id(conversation_id)

        async with SessionLocal() as db:
            await self._run_repo.create(
                db,
                conversation_id=conversation_id,
                thread_id=thread_id,
                user_id=user_id,
            )
            await db.commit()

        files = await self.save_uploaded_files(file_data or [], thread_id, user_id=user_id)

        return {
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "files": files,
        }

    # ── File uploads ──────────────────────────────────────────────────────

    async def add_files_to_conversation(
        self,
        user_id: str,
        conversation_id: str,
        file_data: list[tuple[str, bytes]],
    ) -> dict[str, Any]:
        """Upload additional files to an existing conversation.

        Resolves the authoritative ``thread_id`` from the runs table so the
        storage key stays consistent with the rest of the pipeline.
        Returns the list of saved file metadata.
        """
        meta = await self._get_and_verify_ownership(conversation_id, user_id)
        thread_id = meta["thread_id"]
        files = await self.save_uploaded_files(file_data, thread_id, user_id=user_id)
        return {"conversation_id": conversation_id, "files": files}

    @staticmethod
    async def save_uploaded_files(
        file_data: list[tuple[str, bytes]],
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Save uploaded file contents to the thread's uploads directory.

        Writes to both the local filesystem (sandbox access) and the
        configured storage backend (OBS / MinIO / local).

        Returns list of file metadata dicts (filename, size, path, extension).
        """
        if not file_data:
            return []

        from app.core.storage import LocalStorageBackend, get_storage

        storage = get_storage()
        cfg = get_agent_config()
        path_provider = cfg.path_provider
        uploads_dir = path_provider.get_uploads_dir(thread_id, user_id=user_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)

        uid = user_id or "default"
        virtual_prefix = path_provider.get_virtual_prefix()

        result: list[dict[str, Any]] = []
        for filename, content in file_data:
            safe_name = Path(filename).name
            dest = uploads_dir / safe_name
            dest.write_bytes(content)

            # ── Also upload to remote storage (S3 / MinIO) ──────────────
            if not isinstance(storage, LocalStorageBackend):
                storage_key = f"users/{uid}/threads/{thread_id}/uploads/{safe_name}"
                try:
                    await storage.upload(local_path=dest, key=storage_key)
                except Exception as exc:
                    logger.warning("Failed to upload {} to storage: {}", safe_name, exc)

            result.append(
                {
                    "filename": safe_name,
                    "size": len(content),
                    "path": f"{virtual_prefix}/uploads/{safe_name}",
                    "extension": Path(safe_name).suffix,
                }
            )
            logger.info("Saved uploaded file {} ({} bytes) to {}", safe_name, len(content), dest)

        return result

    # ── Read / Verify ownership ────────────────────────────────────────────

    async def _get_and_verify_ownership(self, conversation_id: str, user_id: int) -> dict[str, Any]:
        """Look up a conversation and verify it belongs to *user_id*.

        Returns the run dict on success.
        Raises 404 if not found, 403 if owned by another user.
        """
        async with SessionLocal() as db:
            run = await self._run_repo.get_by_id(db, conversation_id)

        if run is None:
            raise HTTPException(status_code=404, detail=f"对话 {conversation_id} 不存在")
        if run.user_id is not None and run.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此对话")

        return {
            "conversation_id": run.id,
            "thread_id": run.thread_id,
            "title": run.title,
            "title_pending": run.title_pending,
            "status": run.status,
            "total_tokens": run.total_tokens,
            "cache_read": run.cache_read,
            "cache_creation": run.cache_creation,
            "owner_user_id": run.user_id,
        }

    async def get_conversation(self, conversation_id: str, user_id: int) -> dict[str, Any]:
        """Get a single conversation by id, verifying ownership."""
        return await self._get_and_verify_ownership(conversation_id, user_id)

    # ── List / Delete ─────────────────────────────────────────────────────

    async def list_conversations(self, user_id: str) -> dict:
        """Get all conversations for *user_id* ordered by most recent activity."""
        async with SessionLocal() as db:
            rows = await self._run_repo.get_all(db, user_id=user_id)

        return {
            "conversations": [
                {
                    "conversation_id": r.id,
                    "thread_id": r.thread_id,
                    "title": r.title,
                    "title_pending": r.title_pending,
                    "status": r.status,
                    "total_tokens": r.total_tokens,
                    "cache_read": r.cache_read,
                    "cache_creation": r.cache_creation,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in rows
            ],
        }

    async def delete_conversation(self, conversation_id: str, user_id: int) -> dict:
        """Delete a conversation and all its messages, logs, files.

        Cascading deletes:
        - Messages in the ``messages`` table
        - Run record in the ``runs`` table
        - Sandbox container for the thread (best-effort, AioSandboxProvider only)
        - Per-thread workspace/uploads/outputs directory on disk
        - State log files on disk
        """
        # Verify ownership first
        await self._get_and_verify_ownership(conversation_id, user_id)

        async with SessionLocal() as db:
            run = await self._run_repo.get_by_id(db, conversation_id)
            # run is guaranteed non-None by _get_and_verify_ownership above
            await self._message_repo.delete_by_conversation(db, conversation_id)
            await self._run_repo.delete(db, conversation_id)
            await db.commit()

            thread_id = run.thread_id  # type: ignore[union-attr]

        cfg = get_agent_config()

        # ── 1. Destroy sandbox container (best-effort) ─────────────────
        # Must happen BEFORE deleting the thread directory on Linux —
        # bind-mounted volumes cannot be removed while a container is
        # still using them ("Device or resource busy"). AioSandboxProvider
        # exposes ``destroy()``; LocalSandboxProvider doesn't need this
        # since it has no external resources to release.
        sandbox_provider = cfg.sandbox_provider
        if hasattr(sandbox_provider, "destroy"):
            sandbox_id = hashlib.sha256(thread_id.encode()).hexdigest()[:8]
            try:
                sandbox_provider.destroy(sandbox_id)
                logger.debug("Destroyed sandbox {} for thread {}", sandbox_id, thread_id)
            except Exception:
                logger.opt(exception=True).warning(
                    "Failed to destroy sandbox {} for thread {} (continuing with cleanup)",
                    sandbox_id,
                    thread_id,
                )

        # ── 2. Delete files from remote storage (S3 / MinIO) ───────────
        # Must happen before deleting the thread directory — once the
        # directory is gone we lose track of what to clean up.
        await self._delete_storage_files(thread_id, user_id)

        # ── 3. Delete thread directory on disk (best-effort) ──────────
        try:
            cfg.path_provider.delete_thread_dir(thread_id, user_id=str(user_id))
            logger.info("Deleted thread directory for conversation {}", conversation_id)
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to delete thread directory for conversation {} (may be held by sandbox; will need manual cleanup)",
                conversation_id,
            )

        # ── 4. Delete state logs ──────────────────────────────────────
        delete_conversation_logs(conversation_id, user_id=str(user_id))

        logger.info("Deleted conversation {} (thread_id={})", conversation_id, thread_id)
        return {"conversation_id": conversation_id, "deleted": True}

    @staticmethod
    async def _delete_storage_files(thread_id: str, user_id: int) -> None:
        """Delete all files under the thread's prefix from remote storage.

        Best-effort — failures are logged but never raised, so they don't
        block conversation deletion.

        The thread's storage prefix is ``users/{uid}/threads/{tid}/``.
        """
        from app.core.storage import LocalStorageBackend, get_storage

        storage = get_storage()
        if isinstance(storage, LocalStorageBackend):
            return  # local storage — files deleted via delete_thread_dir

        uid = str(user_id)
        prefix = f"users/{uid}/threads/{thread_id}/"
        try:
            deleted = await storage.delete_prefix(prefix)
        except Exception:
            logger.opt(exception=True).warning(
                "delete_prefix failed for thread {} — remote files may not be cleaned up",
                thread_id,
            )
            return

        if deleted:
            logger.info(
                "Deleted {} storage object(s) for thread {}",
                deleted,
                thread_id,
            )
