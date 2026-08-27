"""Stream result persister — save agent results to database and state log.

Handles all persistence concerns: state log (forensic JSON files), run metadata
(runs table), and structured messages (messages table — interleaved thinking,
reasoning, and tool calls).
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from app.core.config_loader import get_agent_config
from app.core.state_logger import get_model_calls, reset_model_calls, save_state_log
from app.models.database import SessionLocal
from app.repositories.message_repo import MessageRepo
from app.repositories.run_repo import RunRepo
from app.utils import get_model_display_name

# ── Shared title utilities ──────────────────────────────────────────────

# Regex to strip <uploaded_files>...</uploaded_files> block from titles.
_UPLOADED_FILES_BLOCK_RE = re.compile(
    r"<uploaded_files>[\s\S]*?(?:</uploaded_files>|$)\n*",
    re.IGNORECASE,
)


def _strip_title(title: str | None) -> str | None:
    """Remove ``<uploaded_files>`` blocks from a title string."""
    if title is None:
        return None
    cleaned = _UPLOADED_FILES_BLOCK_RE.sub("", title).strip()
    return cleaned or None


def _fallback_title(user_message: str, max_chars: int = 50) -> str:
    """Generate a local fallback title from the user message.

    Mirrors :meth:`TitleMiddleware._fallback_title` so the cancelled /
    early-error paths produce a reasonable title even when the
    middleware hasn't run yet.
    """
    stripped = _UPLOADED_FILES_BLOCK_RE.sub("", user_message).strip()
    if not stripped:
        return ""
    if len(stripped) > max_chars:
        return stripped[:max_chars].rstrip() + "..."
    return stripped


# Tools that can create or modify files in the sandbox.  Used to decide
# whether the post-run file sync (pull from sandbox → upload to OBS) has
# anything to do.  A pure-text turn (e.g. a self-introduction) runs none of
# these, so we skip the sandbox pull entirely instead of spinning up a fresh
# sandbox Pod just to list three empty directories.
_FILE_PRODUCING_TOOLS = frozenset({"write_file", "bash", "str_replace", "task"})


def _turn_produced_files(steps: list[dict[str, Any]], file_metadatas: str | None) -> bool:
    """Return True if this turn may have created files worth syncing.

    True when the user attached a file, or any file-producing tool was
    invoked at all (``tool_start`` or ``tool_end``).  Being conservative —
    returning True whenever we're unsure — is intentional: an unnecessary
    sync is harmless, but skipping a real sync would silently drop files.
    """
    if file_metadatas:
        return True
    return any(step.get("tool") in _FILE_PRODUCING_TOOLS for step in steps)


class StreamResultPersister:
    """Persist agent stream results to database and state log.

    Args:
        run_repo: Repository for ``runs`` table CRUD.
        message_repo: Repository for ``messages`` table CRUD.
        file_tree_builder: FileTreeBuilder instance for workspace sanitization.
    """

    def __init__(
        self,
        run_repo: RunRepo,
        message_repo: MessageRepo,
        file_tree_builder: Any,
        sandbox_provider: Any = None,
    ) -> None:
        self._run_repo = run_repo
        self._message_repo = message_repo
        self._file_tree = file_tree_builder
        self._sandbox_provider = sandbox_provider

    # ── Public API ────────────────────────────────────────────────────────

    async def persist(
        self,
        *,
        conversation_id: str,
        thread_id: str,
        user_id: str,
        user_message: str,
        all_tokens: list[str],
        assistant_message_id: str,
        steps: list[dict[str, Any]],
        state_before: dict[str, Any] | None = None,
        state_after: dict[str, Any] | None = None,
        file_metadatas: str | None = None,
        prev_status: str | None = None,
        status: str,
        error_message: str | None = None,
        error: Exception | None = None,
        recoverable: bool = False,
        model_name: str | None = None,
    ) -> None:
        """Save state log and persist stream results to database.

        This is the single entry point for all persistence after a stream
        completes (success, error, or cancellation).
        """
        # ── State log — forensic traceability ──────────────────────────
        model_calls = get_model_calls()
        save_state_log(
            conversation_id=conversation_id,
            thread_id=thread_id,
            user_message=user_message,
            state_before=state_before,
            state_after=state_after,
            error=error,
            recursion_limit=150,
            model_id=get_model_display_name(model_name),
            user_id=user_id,
            model_calls=model_calls if model_calls else None,
        )
        reset_model_calls()

        # ── Database persistence ───────────────────────────────────────
        await self._persist_stream_result(
            conversation_id=conversation_id,
            thread_id=thread_id,
            user_id=user_id,
            user_message=user_message,
            all_tokens=all_tokens,
            assistant_message_id=assistant_message_id,
            steps=steps,
            state_after=state_after,
            file_metadatas=file_metadatas,
            prev_status=prev_status,
            status=status,
            error_message=error_message,
            recoverable=recoverable,
        )

    # ── Private persistence ───────────────────────────────────────────────

    async def _persist_stream_result(
        self,
        *,
        conversation_id: str,
        thread_id: str,
        user_id: str,
        user_message: str,
        all_tokens: list[str],
        assistant_message_id: str,
        steps: list[dict[str, Any]],
        state_after: dict[str, Any] | None,
        file_metadatas: str | None = None,
        prev_status: str | None = None,
        status: str = "completed",
        error_message: str | None = None,
        recoverable: bool = False,
    ) -> None:
        """Persist a streaming run result (normal, cancelled, or error).

        Args:
            status: ``"completed"`` for normal finish, ``"cancelled"`` for
                user-initiated stop, ``"error"`` for failures, ``"step_limit"``
                for a recoverable step-limit interruption.
            error_message: Frontend-visible error text; persisted as an assistant
                message when *status* is ``"error"``, so the error is visible in
                message history after a page refresh.
            recoverable: True for a recoverable interruption (e.g. step limit)
                where the checkpoint is intact and the user can continue.  The
                message is then persisted with ``event_type="step_limit"`` so the
                frontend renders a hint rather than a hard error.
        """
        try:
            # ── Clean up garbage artifacts before persistence ──────────
            self._file_tree.sanitize_workspace(thread_id, user_id)

            full_response = "".join(all_tokens)
            title = state_after.get("title") if state_after else None
            title = _strip_title(title)
            # No local fallback here.  The preliminary title was already written
            # at stream start (set_title with the truncated user message), and an
            # AI title may have been persisted early by TitleMiddleware.  A local
            # fallback computed here would clobber either of those on a
            # cancelled/error turn where state_after is empty — so leave title as
            # None and let _save_chat_to_db preserve whatever is already set.
            messages_raw = state_after.get("messages", []) if state_after else []
            total_tokens = self._extract_total_tokens(messages_raw)
            cache_read, cache_creation = self._extract_cache_metrics(messages_raw)
            await self._save_chat_to_db(
                conversation_id=conversation_id,
                thread_id=thread_id,
                user_id=user_id,
                user_message=user_message,
                assistant_response=full_response,
                assistant_message_id=assistant_message_id,
                steps=steps,
                title=title,
                total_tokens=total_tokens,
                cache_read=cache_read,
                cache_creation=cache_creation,
                file_metadatas=file_metadatas,
                prev_status=prev_status,
                status=status,
                user_message_already_saved=True,
                error_message=error_message,
                recoverable=recoverable,
            )

            # ── Sync thread files to remote storage (OBS / MinIO) ──────────
            # Skip for turns that produced no files: a pure-text turn (e.g.
            # a self-introduction) has nothing to pull, and syncing would
            # otherwise acquire / create a fresh sandbox Pod (blocking the
            # event loop for minutes on image pull) just to list empty dirs.
            # Also skip for cancelled turns: the user stopped the run and
            # wants the stream to end immediately, not to wait for a sandbox
            # pull + object-store upload that would add seconds of lag.
            if status != "cancelled" and _turn_produced_files(steps, file_metadatas):
                await self._sync_thread_files_to_storage(thread_id, user_id)
            else:
                logger.info(
                    "Skipping file sync for thread {} — turn produced no files or was cancelled",
                    thread_id,
                )
        except Exception:
            logger.exception(
                "Failed to persist chat to database for conversation {}",
                conversation_id,
            )
        finally:
            # In pool (resident Pod) mode the sandbox slot must be returned to
            # the pool at the end of every run — even when file sync was skipped
            # (cancelled, or a pure-text turn with no sandbox work).  This is
            # idempotent: if the sandbox was already released by the file pull,
            # or was never acquired, it is a no-op.
            await self._release_thread_sandbox(thread_id)

    async def _sync_thread_files_to_storage(self, thread_id: str, user_id: str) -> None:
        """Sync agent-generated files to the remote storage backend.

        This is a best-effort post-persistence step — failures are logged
        but never surfaced to the user.

        Covers all three per-thread directories: outputs, workspace, and
        uploads.  When a remote sandbox provider is available (K8s
        provisioner mode), files are first pulled from the sandbox
        container via its HTTP API before being uploaded.
        """
        from app.core.storage import LocalStorageBackend, get_storage

        storage = get_storage()
        if isinstance(storage, LocalStorageBackend):
            return  # local storage — files already on disk

        cfg = get_agent_config()
        pp = cfg.path_provider

        # ── Pull files from remote sandbox if needed ───────────────────
        if self._sandbox_provider is not None:
            try:
                await self._pull_sandbox_files(thread_id, user_id)
            except Exception:
                logger.exception(
                    "Failed to pull files from sandbox for thread {} — files may not be in storage",
                    thread_id,
                )

        # ── Upload all three buckets ────────────────────────────────────
        base_dir = pp.get_base_dir()
        buckets = [
            ("outputs", pp.get_outputs_dir),
            ("workspace", pp.get_workspace_dir),
            ("uploads", pp.get_uploads_dir),
        ]
        total_uploaded = 0
        for bucket_name, get_dir_fn in buckets:
            bucket_dir = get_dir_fn(thread_id, user_id=user_id)
            if not bucket_dir.exists() or not bucket_dir.is_dir():
                continue

            for file_path in bucket_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                # Skip skill-injection artifacts — these are internal
                # reference files injected at runtime, not user data.
                if "/.skills/" in str(file_path).replace("\\", "/"):
                    continue
                try:
                    rel = file_path.relative_to(base_dir)
                    storage_key = str(rel).replace("\\", "/")
                    await storage.upload(local_path=file_path, key=storage_key)
                    total_uploaded += 1
                except Exception:
                    logger.exception(
                        "Failed to upload {} to storage",
                        file_path.name,
                    )

        if total_uploaded:
            logger.info(
                "Synced {} file(s) to storage for thread {}",
                total_uploaded,
                thread_id,
            )

    async def _pull_sandbox_files(self, thread_id: str, user_id: str) -> None:
        """Pull per-thread files from the sandbox container to local disk.

        This is necessary in K8s provisioner mode where the sandbox runs
        in a remote Pod and its filesystem is NOT accessible from the
        backend Pod.  We acquire the sandbox via the provider (it should
        still be in the warm pool after the agent run), list files under
        ``/mnt/user-data/{outputs,workspace,uploads}/``, and write them
        to the local directories so that :meth:`_sync_thread_files_to_storage`
        can upload them in the next step.

        This is a best-effort helper — failures are logged at the warning
        level but never raised to the caller.
        """

        provider = self._sandbox_provider
        sandbox_id = None
        try:
            sandbox_id = await asyncio.to_thread(provider.acquire, thread_id)
            sandbox = provider.get(sandbox_id)
            if sandbox is None:
                logger.warning(
                    "Sandbox not available for thread {} — cannot pull files",
                    thread_id,
                )
                return
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to acquire sandbox for thread {} — files will not be synced from sandbox",
                thread_id,
            )
            return

        try:
            cfg = get_agent_config()
            pp = cfg.path_provider

            virtual_buckets = [
                ("/mnt/user-data/outputs", pp.get_outputs_dir(thread_id, user_id=user_id)),
                ("/mnt/user-data/workspace", pp.get_workspace_dir(thread_id, user_id=user_id)),
                ("/mnt/user-data/uploads", pp.get_uploads_dir(thread_id, user_id=user_id)),
            ]

            pulled = 0
            for virtual_root, local_dir in virtual_buckets:
                try:
                    files = await asyncio.to_thread(sandbox.list_files, virtual_root)
                except Exception:
                    logger.opt(exception=True).warning(
                        "Failed to list {} in sandbox — skipping bucket",
                        virtual_root,
                    )
                    continue

                for file_path in files:
                    try:
                        # Compute the relative path inside the virtual bucket
                        rel = file_path.removeprefix(virtual_root).lstrip("/")
                        if not rel:
                            continue
                        # Skip skill-injection artifacts — internal runtime
                        # files, not user-generated content.
                        if "/.skills/" in file_path or rel.startswith(".skills/"):
                            continue
                        content = await asyncio.to_thread(sandbox.download_file_bytes, file_path)
                        if not content:
                            # Fallback: try reading as text (for small/plain files
                            # where the streaming download may not be supported)
                            text = await asyncio.to_thread(sandbox.read_file, file_path)
                            if text and not text.startswith("Error:"):
                                content = text.encode("utf-8")
                            else:
                                continue
                        local_path = local_dir / rel
                        local_path.parent.mkdir(parents=True, exist_ok=True)
                        local_path.write_bytes(content)
                        pulled += 1
                    except Exception:
                        logger.opt(exception=True).warning(
                            "Failed to pull file {} from sandbox",
                            file_path,
                        )

            if pulled:
                logger.info("Pulled {} file(s) from sandbox for thread {}", pulled, thread_id)
        finally:
            try:
                # Offload to a thread — in resident-pool mode ``release`` runs a
                # blocking clear command that must not stall the event loop.
                await asyncio.to_thread(provider.release, sandbox_id)
            except Exception:
                logger.opt(exception=True).warning(
                    "Failed to release sandbox {} after file pull",
                    sandbox_id,
                )

    async def _release_thread_sandbox(self, thread_id: str) -> None:
        """Release the sandbox bound to *thread_id* (best-effort, idempotent).

        Guarantees the resident Pod slot is returned to the pool at the end of
        every run.  Safe to call when no sandbox is bound (pure-text turns) or
        when the file-pull path already released it.

        Only runs in resident-pool mode — in local Docker / subprocess mode
        there is no slot to leak, and releasing would needlessly move a still-
        bound sandbox into the warm pool between turns of the same conversation.
        """
        provider = self._sandbox_provider
        if provider is None:
            return
        if not getattr(provider, "pool_enabled", False):
            return
        release_thread = getattr(provider, "release_thread", None)
        if release_thread is None:
            return
        try:
            await asyncio.to_thread(release_thread, thread_id)
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to release sandbox for thread {}",
                thread_id,
            )

    async def _save_chat_to_db(
        self,
        conversation_id: str,
        thread_id: str,
        user_id: str,
        user_message: str,
        assistant_response: str,
        assistant_message_id: str,
        steps: list[dict[str, Any]],
        title: str | None = None,
        total_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
        file_metadatas: str | None = None,
        prev_status: str | None = None,
        status: str = "completed",
        user_message_already_saved: bool = False,
        error_message: str | None = None,
        recoverable: bool = False,
    ) -> None:
        """Persist a chat turn (user + interleaved thinking + tool calls).

        Args:
            status: Run status — ``"completed"``, ``"cancelled"``, ``"error"``,
                or ``"step_limit"``.
            user_message_already_saved: If True, skip the user message insert
                — already written at stream start for immediate visibility.
            error_message: When *status* is ``"error"``, this text is persisted
                as an assistant message so the error is visible in message history.
        """
        base_time = datetime.now(UTC)
        _seq = 0

        def _now() -> datetime:
            nonlocal _seq
            _seq += 1
            return base_time + timedelta(microseconds=_seq)

        async with SessionLocal() as db:
            # ── Preserve run metadata across turns ───────────────────────
            existing = await self._run_repo.get_by_id(db, conversation_id)
            effective_status = status
            effective_title = title
            effective_tokens = total_tokens
            effective_cache_read = cache_read
            effective_cache_creation = cache_creation

            if existing is not None:
                # Never downgrade from "completed" to "error" — the
                # conversation had a successful turn already.  Compare
                # against ``prev_status`` (captured before the "running"
                # marker was written at turn start), since ``existing.status``
                # is "running" while a turn is in flight.
                if prev_status == "completed" and status == "error":
                    effective_status = "completed"

                # Preserve the existing title unless the new turn
                # produced a real (agent-generated) one.
                if existing.title and not title:
                    effective_title = existing.title

                # Accumulate token counts across turns.
                effective_tokens = existing.total_tokens + total_tokens
                effective_cache_read = (existing.cache_read or 0) + cache_read
                effective_cache_creation = (existing.cache_creation or 0) + cache_creation

            # Run record
            await self._run_repo.upsert(
                db,
                conversation_id,
                thread_id,
                user_id,
                title=effective_title,
                total_tokens=effective_tokens,
                cache_read=effective_cache_read,
                cache_creation=effective_cache_creation,
                status=effective_status,
            )
            await db.flush()

            # User message (may have been written early at stream start)
            if not user_message_already_saved:
                await self._message_repo.create(
                    db,
                    conversation_id=conversation_id,
                    thread_id=thread_id,
                    role="user",
                    content=user_message,
                    event_type="message",
                    file_metadata=file_metadatas,
                    created_at=_now(),
                )

            # Interleaved thinking + tool calls (chronological order)
            pending_tool: dict[str, Any] | None = None

            async def _flush_pending() -> None:
                nonlocal pending_tool
                if pending_tool is not None:
                    await self._message_repo.create(
                        db,
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        role="tool",
                        content="",
                        event_type="tool_call",
                        tool_name=pending_tool.get("tool"),
                        tool_input=pending_tool.get("input"),
                        tool_output=pending_tool.get("output", ""),
                        description=pending_tool.get("description"),
                        duration_ms=pending_tool.get("duration_ms"),
                        created_at=_now(),
                    )
                    pending_tool = None

            for step in steps:
                if step["type"] == "thinking":
                    await _flush_pending()
                    await self._message_repo.create(
                        db,
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        role="assistant",
                        content=step.get("content", ""),
                        event_type="message",
                        created_at=_now(),
                    )
                elif step["type"] == "reasoning":
                    await _flush_pending()
                    await self._message_repo.create(
                        db,
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        role="assistant",
                        content=step.get("content", ""),
                        event_type="reasoning",
                        created_at=_now(),
                    )
                elif step["type"] == "tool_start":
                    await _flush_pending()
                    pending_tool = step
                elif step["type"] == "tool_end" and pending_tool is not None:
                    pending_tool["output"] = step.get("output", "")
                    await _flush_pending()

            await _flush_pending()

            # ── Persist error message ──────────────────────────────────
            # Recoverable interruptions (step limit) are stored under a
            # distinct event_type so the frontend can render them as a hint
            # ("continue the task") rather than a hard error.
            if error_message:
                await self._message_repo.create(
                    db,
                    conversation_id=conversation_id,
                    thread_id=thread_id,
                    role="assistant",
                    content=error_message,
                    event_type="step_limit" if recoverable else "error",
                    created_at=_now(),
                )

            await db.commit()

    # ── Static helpers ────────────────────────────────────────────────────

    @staticmethod
    def _extract_total_tokens(messages: list) -> int:
        total = 0
        for msg in messages:
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                total += usage.get("total_tokens", 0)
        return total

    @staticmethod
    def _extract_cache_metrics(messages: list) -> tuple[int, int]:
        """Extract cumulative cache_read and cache_creation from messages."""
        cache_read = 0
        cache_creation = 0
        for msg in messages:
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                details = usage.get("input_token_details", {}) or {}
                cache_read += details.get("cache_read", 0) or 0
                cache_creation += details.get("cache_creation", 0) or 0
        return cache_read, cache_creation
