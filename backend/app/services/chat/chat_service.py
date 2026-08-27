"""Chat service — agent execution orchestration + persistence.

The service layer owns all business logic: running the agent,
collecting steps, persisting to the database, and saving state logs.
Routes only handle HTTP concerns (parsing params, SSE formatting).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
import zipfile
from collections.abc import AsyncGenerator
from typing import Any

from agent_sdk.community.skillhub import CANCEL_EVENT_CTX
from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from loguru import logger

from app.core.agent import get_agent
from app.core.config_loader import get_agent_config
from app.core.storage import LocalStorageBackend, get_storage
from app.models.database import SessionLocal
from app.repositories.message_repo import MessageRepo
from app.repositories.run_repo import RunRepo
from app.repositories.skill_repo import SkillRepo
from app.services.chat.file_tree_builder import FileTreeBuilder
from app.services.chat.post_hoc_error_detector import PostHocErrorDetector
from app.services.chat.stream_event_handler import StreamEventHandler
from app.services.chat.stream_result_persister import StreamResultPersister, _fallback_title
from app.services.chat.title_service import generate_title
from app.utils import make_config


class ChatService:
    """Orchestrate agent execution and persistence for chat endpoints."""

    def __init__(self) -> None:
        self._run_repo = RunRepo()
        self._message_repo = MessageRepo()
        self._file_tree = FileTreeBuilder()
        cfg = get_agent_config()
        self._persister = StreamResultPersister(
            self._run_repo,
            self._message_repo,
            self._file_tree,
            sandbox_provider=cfg.sandbox_provider if cfg else None,
        )

    # ── Public API ────────────────────────────────────────────────────────

    async def execute_stream(
        self,
        message: str,
        conversation_id: str,
        user_id: str,
        thinking_enabled: bool = True,
        model_name: str | None = None,
        file_metadatas: str | None = None,
        skill_name: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run the agent and yield structured stream events.

        Args:
            message: The user's input text.
            conversation_id: Must be a valid conversation created via POST /conversations.
            user_id: The authenticated user owning this conversation.
            thinking_enabled: Per-message deep thinking toggle.
            model_name: Model to use (config.yaml models[].name).  ``None`` uses default.
            skill_name: Optional skill the user explicitly selected via the ``@``
                mention.  When set, a lightweight directive is prepended to the
                message so the agent loads and follows that skill.
            cancel_event: Optional :class:`asyncio.Event` for cooperative cancellation.

        Yields dicts with keys:
          ``type`` — one of ``run_start``, ``thinking_start``, ``token``,
          ``reasoning``, ``thinking_end``, ``tool_start``, ``tool_end``,
          ``error``, ``run_end``.
        """
        # ── 1. Setup ───────────────────────────────────────────────────
        cfg = await self._get_conversation_config(conversation_id, user_id)
        thread_id = cfg["thread_id"]
        assistant_message_id = str(uuid.uuid4())
        config = make_config(thread_id)
        agent = get_agent(thinking_enabled=thinking_enabled, model_name=model_name)

        # ── 2. Capture state before ────────────────────────────────────
        state_before: dict[str, Any] | None = None
        try:
            bs = await agent.aget_state(config)
            if bs is not None and bs.values:
                state_before = dict(bs.values)
            elif bs is not None:
                state_before = {}
        except Exception:
            pass

        # ── 3. Yield run_start ─────────────────────────────────────────
        yield {
            "type": "run_start",
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "assistant_message_id": assistant_message_id,
        }

        # ── 4. Save preliminary title + user message ───────────────────
        _prelim_title = _fallback_title(message)
        prev_status: str | None = None
        _should_generate_title = False
        try:
            async with SessionLocal() as db:
                # Capture the status before this turn so the "never downgrade
                # completed → error" guard in the persister can still compare
                # against the previous turn's outcome — writing "running" here
                # would otherwise erase that information.
                _run = await self._run_repo.get_by_id(db, conversation_id)
                prev_status = _run.status if _run else None
                # 占位标题只在首轮写入 —— 后续追问不能把已生成的 AI 标题
                # 覆盖成本轮消息的截断占位标题（标题只生成一次、之后保持不变）。
                if _prelim_title and (not _run or not _run.title):
                    await self._run_repo.set_title(db, conversation_id, _prelim_title)
                    await self._run_repo.set_title_pending(db, conversation_id, True)
                    _should_generate_title = True
                await self._run_repo.set_status(db, conversation_id, "running")
                await self._message_repo.create(
                    db,
                    conversation_id=conversation_id,
                    thread_id=thread_id,
                    role="user",
                    content=message,
                    event_type="message",
                    file_metadata=file_metadatas,
                )
                await db.commit()
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to persist preliminary data for conversation {}",
                conversation_id,
            )

        # 后台异步生成 AI 标题（与 agent 执行隔离，不阻塞回合结束）。
        # 标题模型调用可能很慢（网关延迟波动），fire-and-forget；完成后
        # 经 _persist_title 写库，前端通过 GET /conversations 轮询同步。
        if _should_generate_title:
            asyncio.create_task(self._generate_title_async(conversation_id, message))

        # ── 5. Run agent event loop ────────────────────────────────────
        # 用户显式指定的技能（@ 功能）以「轻量注入」方式前置到消息前——
        # 只下指令让 agent 先 read_skill，不把 SKILL.md 全文塞进上下文。
        # 这里改的是喂给 agent 的 human_msg，不影响第 4 步持久化的原始 message。
        skill_directive = await self._build_skill_directive(skill_name, user_id)
        human_msg = HumanMessage(
            content=(skill_directive + message) if skill_directive else message,
        )
        handler = StreamEventHandler(
            agent=agent,
            conversation_id=conversation_id,
            cancel_event=cancel_event,
        )
        try:
            async for evt in handler.process(human_msg, config):
                yield evt
        finally:
            # Restore the cancel-event context variable so it does not
            # leak into other tasks that reuse this thread.
            if handler.cancel_token is not None:
                CANCEL_EVENT_CTX.reset(handler.cancel_token)

        # ── 6. Capture state after ─────────────────────────────────────
        # For a cancelled turn the graph may still be unwinding in the
        # background, so skip the checkpoint read — it is only used for the
        # title/token extraction, which a stopped turn doesn't need, and it
        # could otherwise block on the checkpointer mid-cancellation.
        state_after: dict[str, Any] | None = None
        if not handler.cancelled:
            try:
                rs = await agent.aget_state(config)
                if rs and rs.values:
                    state_after = dict(rs.values)
            except Exception:
                pass

        # ── 7. Post-hoc error detection ────────────────────────────────
        if handler.error is None and state_after and not handler.cancelled:
            try:
                post_hoc = PostHocErrorDetector.detect(
                    state_after=state_after,
                    state_before=state_before,
                    cancelled=handler.cancelled,
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.exception(
                    "[PostHocErrorDetector] detect() raised for conversation {}",
                    conversation_id,
                )
                post_hoc = None

            if post_hoc is not None:
                for text in post_hoc.clarification_texts:
                    handler.all_tokens.append(text)
                    yield {"type": "token", "content": text}
                if post_hoc.fatal_error:
                    handler.error = post_hoc.fatal_error
                    handler.error_message = post_hoc.error_message
                    yield {"type": "error", "message": post_hoc.error_message}

        # ── 8. Persist + yield run_end ─────────────────────────────────
        # Each persist path is wrapped individually so the log tells you
        # exactly which status path (cancelled/error/completed) failed.
        # The outermost try/except guarantees run_end is always yielded —
        # even if the error-recovery path itself fails.
        try:
            if handler.cancelled:
                # Yield run_end FIRST so the client is told "stopped"
                # immediately — persistence (state log, DB writes, and any
                # best-effort file sync) then completes in the background
                # relative to the client, instead of delaying the stop by the
                # duration of those post-steps.
                yield {
                    "type": "run_end",
                    "conversation_id": conversation_id,
                    "finish_reason": "cancelled",
                }
                try:
                    await self._persister.persist(
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        user_message=message,
                        all_tokens=handler.all_tokens,
                        assistant_message_id=assistant_message_id,
                        steps=handler.steps,
                        state_before=state_before,
                        state_after=state_after,
                        file_metadatas=file_metadatas,
                        prev_status=prev_status,
                        status="cancelled",
                        model_name=model_name,
                    )
                except Exception:
                    logger.exception(
                        "[StreamResultPersister] persist (cancelled) failed for conversation {}",
                        conversation_id,
                    )
                return

            if handler.error:
                try:
                    await self._persister.persist(
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        user_message=message,
                        all_tokens=handler.all_tokens,
                        assistant_message_id=assistant_message_id,
                        steps=handler.steps,
                        state_before=state_before,
                        state_after=state_after,
                        file_metadatas=file_metadatas,
                        prev_status=prev_status,
                        status="step_limit" if handler.recoverable else "error",
                        error_message=handler.error_message,
                        error=handler.error,
                        recoverable=handler.recoverable,
                        model_name=model_name,
                    )
                except Exception:
                    logger.exception(
                        "[StreamResultPersister] persist (error) failed for conversation {}",
                        conversation_id,
                    )
                yield {
                    "type": "run_end",
                    "conversation_id": conversation_id,
                    "finish_reason": "error",
                }
                return

            # Normal completion
            try:
                await self._persister.persist(
                    conversation_id=conversation_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    user_message=message,
                    all_tokens=handler.all_tokens,
                    assistant_message_id=assistant_message_id,
                    steps=handler.steps,
                    state_before=state_before,
                    state_after=state_after,
                    file_metadatas=file_metadatas,
                    prev_status=prev_status,
                    status="completed",
                    model_name=model_name,
                )
            except Exception:
                logger.exception(
                    "[StreamResultPersister] persist (completed) failed for conversation {}",
                    conversation_id,
                )
            yield {
                "type": "run_end",
                "conversation_id": conversation_id,
                "finish_reason": "stop",
            }
        except Exception:
            logger.exception(
                "[ChatService] yield run_end failed for conversation {} (original error: {})",
                conversation_id,
                type(handler.error).__name__ if handler.error else "none",
            )
            from app.core.state_logger import reset_model_calls

            reset_model_calls()
            yield {
                "type": "run_end",
                "conversation_id": conversation_id,
                "finish_reason": "error",
            }

    async def get_messages(self, conversation_id: str, user_id: int) -> dict[str, Any]:
        """Get structured message history for a conversation."""
        await self._verify_ownership(conversation_id, user_id)
        async with SessionLocal() as db:
            rows = await self._message_repo.get_by_conversation(db, conversation_id)

        return {
            "conversation_id": conversation_id,
            "messages": [self._build_message_dict(m) for m in rows],
        }

    # ── File tree delegation ───────────────────────────────────────────────

    async def build_file_tree(self, conversation_id: str, user_id: int) -> dict[str, Any]:
        """Build a recursive file tree for outputs, workspace, and uploads."""
        thread_id = await self._get_thread_id(conversation_id, user_id)
        return await self._file_tree.build_file_tree(conversation_id, thread_id, user_id)

    def resolve_file_path(self, virtual_path: str, thread_id: str, *, user_id: str | None = None) -> Any:
        """Resolve a virtual sandbox path to a physical filesystem path."""
        return self._file_tree.resolve_file_path(virtual_path, thread_id, user_id=user_id)

    def get_file_info(self, virtual_path: str, thread_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        """Return file metadata (size, MIME type, previewable flag)."""
        return self._file_tree.get_file_info(virtual_path, thread_id, user_id=user_id)

    def virtual_path_to_storage_key(self, virtual_path: str, thread_id: str, *, user_id: str | None = None) -> str:
        """Convert a virtual sandbox path to a storage object key.

        Examples:
            ``/mnt/user-data/outputs/foo.pdf``
            → ``users/123/threads/tid/outputs/foo.pdf``
        """
        physical = self._file_tree.resolve_file_path(virtual_path, thread_id, user_id=user_id)
        cfg = get_agent_config()
        base_dir = cfg.path_provider.get_base_dir()
        try:
            rel = physical.resolve().relative_to(base_dir)
        except ValueError:
            raise ValueError(f"File path {physical} is outside base storage directory {base_dir}")
        return str(rel).replace("\\", "/")

    # ── Directory download ─────────────────────────────────────────────────

    async def download_directory(self, conversation_id: str, virtual_path: str, user_id: str) -> dict[str, Any]:
        """打包下载整个目录为 zip，返回临时文件路径与下载文件名。

        优先支持 S3/远程存储：逐个对象边下载边写入 zip，内存占用受
        ``download_stream`` 的 chunk 大小限制，大目录不会一次性读入内存。
        本地存储则递归打包磁盘目录。
        """
        thread_id = await self._get_thread_id(conversation_id, user_id)
        dir_name = self._directory_display_name(virtual_path)
        storage = get_storage()

        if isinstance(storage, LocalStorageBackend):
            return self._build_local_directory_zip(virtual_path, thread_id, user_id=user_id, dir_name=dir_name)

        return await self._build_s3_directory_zip(virtual_path, thread_id, user_id=user_id, dir_name=dir_name)

    @staticmethod
    def _directory_display_name(virtual_path: str) -> str:
        """从虚拟路径取目录名，作为 zip 下载文件名。"""
        stripped = virtual_path.rstrip("/")
        if not stripped or stripped == "/":
            return "download"
        return stripped.rsplit("/", 1)[-1] or "download"

    async def _build_s3_directory_zip(
        self,
        virtual_path: str,
        thread_id: str,
        *,
        user_id: str,
        dir_name: str,
    ) -> dict[str, Any]:
        """将 S3 目录前缀下的所有对象流式打包为 zip（写到磁盘临时文件）。"""
        storage = get_storage()

        try:
            prefix = self.virtual_path_to_storage_key(virtual_path, thread_id, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        objects = await storage.list_objects(prefix)
        file_keys = [obj["key"] for obj in objects if not obj["key"].endswith("/")]
        if not file_keys:
            raise HTTPException(status_code=404, detail=f"目录不存在或为空: {virtual_path}")

        tmp_path = self._make_tmp_zip_path()
        try:
            prefix_slash = prefix.rstrip("/") + "/"
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for key in file_keys:
                    arcname = self._zip_arcname(key, prefix_slash)
                    if arcname is None:
                        continue
                    with zf.open(arcname, "w") as dest:
                        async for chunk in storage.download_stream(key):
                            dest.write(chunk)
        except HTTPException:
            self._remove_tmp_file(tmp_path)
            raise
        except Exception as exc:
            logger.exception("download-dir: failed to zip S3 directory {} for conversation {}", prefix, thread_id)
            self._remove_tmp_file(tmp_path)
            raise HTTPException(status_code=502, detail="打包目录失败，请稍后重试") from exc

        return {"tmp_path": tmp_path, "filename": f"{dir_name}.zip"}

    def _build_local_directory_zip(
        self,
        virtual_path: str,
        thread_id: str,
        *,
        user_id: str,
        dir_name: str,
    ) -> dict[str, Any]:
        """将本地磁盘目录递归打包为 zip。"""
        try:
            physical = self._file_tree.resolve_file_path(virtual_path, thread_id, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not physical.is_dir():
            raise HTTPException(status_code=404, detail=f"目录不存在: {virtual_path}")

        tmp_path = self._make_tmp_zip_path()
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                for file in sorted(physical.rglob("*")):
                    if file.is_file():
                        zf.write(file, arcname=file.relative_to(physical).as_posix())
        except Exception as exc:
            logger.exception("download-dir: failed to zip local directory {}", physical)
            self._remove_tmp_file(tmp_path)
            raise HTTPException(status_code=502, detail="打包目录失败，请稍后重试") from exc

        return {"tmp_path": tmp_path, "filename": f"{dir_name}.zip"}

    @staticmethod
    def _make_tmp_zip_path() -> str:
        """创建磁盘临时 zip 文件（关闭句柄后由调用方按路径使用）。"""
        tmp = tempfile.NamedTemporaryFile(prefix="skillhub-dir-", suffix=".zip", delete=False)
        tmp.close()
        return tmp.name

    @staticmethod
    def _remove_tmp_file(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    @staticmethod
    def _zip_arcname(key: str, prefix_slash: str) -> str | None:
        """计算对象在 zip 内的相对路径；跳过目录标记与不安全路径。"""
        if not key.startswith(prefix_slash):
            return None
        rel = key[len(prefix_slash) :]
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            return None
        return rel

    # ── Authentication / authorization ─────────────────────────────────────

    async def _verify_ownership(self, conversation_id: str, user_id: int) -> None:
        """Verify *user_id* owns *conversation_id*, or raise 403/404."""
        await self._get_thread_id(conversation_id, user_id)

    async def _get_thread_id(self, conversation_id: str, user_id: int) -> str:
        """Return the authoritative ``thread_id`` for a conversation.

        Reads ``run.thread_id`` from the runs table — the single source of
        truth for thread_id — and verifies ownership, raising 404/403 as
        needed.  The upload path (``execute_stream``) and the display path
        (file tree / file serving) both resolve thread_id from the runs
        table, so they never diverge.
        """
        async with SessionLocal() as db:
            run = await self._run_repo.get_by_id(db, conversation_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"对话 {conversation_id} 不存在")
        if run.user_id is not None and run.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此对话")
        return run.thread_id

    # ── Private helpers ────────────────────────────────────────────────────

    async def _build_skill_directive(self, skill_name: str | None, user_id: str) -> str:
        """把用户显式指定的技能转成注入到消息前的指令块。

        轻量注入：只告诉 agent「必须用该技能、先 ``read_skill`` 加载」，不把
        SKILL.md 全文塞进上下文。

        白名单校验与 ``read_skill`` 的可见集合保持一致，覆盖两类来源：
        * 内置技能 —— 文件系统 ``skills/`` 目录里已启用的；
        * 自定义技能 —— DB ``skills`` 表中对当前用户可用（作者本人任意状态，
          或已 ``approved`` 且当前用户已「添加」）。
        未知/不可用的一律拒绝，仅告警并返回空串（不注入、也不打断对话），
        防止注入任意 skill_name。
        """
        if not skill_name:
            return ""

        from agent_sdk.skills import load_skills

        from app.core.agent import get_skills_dir

        # 1) 内置技能：文件系统白名单
        builtin = {s.name: s for s in load_skills(get_skills_dir(), enabled_only=True)}
        target = builtin.get(skill_name)
        if target is not None:
            return (
                f"<explicit_skill>\n用户已显式指定使用技能「{target.name}」：{target.description}\n"
                f"请先调用 read_skill('{target.name}') 加载该技能，并严格按其工作流执行，不要自行偏离。\n</explicit_skill>\n\n"
            )

        # 2) 自定义技能（我的 / 已添加）：DB 白名单
        async with SessionLocal() as db:
            skill = await SkillRepo.get_by_name(db, skill_name)
            if skill is None:
                logger.warning("Rejected unknown skill {!r}; no directive injected", skill_name)
                return ""
            if skill.author_id != user_id:
                # 非作者：需已审核通过且已「添加」
                if skill.review_status != "approved":
                    logger.warning(
                        "Rejected unavailable skill {!r} (status={}); no directive injected",
                        skill_name,
                        skill.review_status,
                    )
                    return ""
                added = await SkillRepo.get_added_names(db, user_id)
                if skill_name not in added:
                    logger.warning("Rejected not-added skill {!r}; no directive injected", skill_name)
                    return ""

        display_name = skill.display_name or skill.name
        description = skill.description or ""
        return (
            f"<explicit_skill>\n用户已显式指定使用技能「{display_name}」：{description}\n"
            f"请先调用 read_skill('{skill_name}') 加载该技能，并严格按其工作流执行，不要自行偏离。\n</explicit_skill>\n\n"
        )

    async def _generate_title_async(self, conversation_id: str, user_message: str) -> None:
        """后台异步生成 AI 标题并写库（fire-and-forget，与 agent 执行隔离）。

        由 ``asyncio.create_task`` 在首轮发起，标题模型调用可能很慢
        （网关延迟波动），放在后台任务里执行、不阻塞回合结束。完成后经
        :meth:`_persist_title` 写库并清除 ``title_pending``，前端通过
        ``GET /conversations`` 轮询同步进度。

        无论成功、失败还是模型缺失，``finally`` 都会清除 ``title_pending``
        —— 避免标题卡住时前端无限轮询；生成失败则保留占位标题。
        """
        title: str | None = None
        try:
            cfg = get_agent_config()
            model = cfg.create_title_model() if cfg else None
            if model is not None:
                prompts = cfg.middleware_deps.title_prompts if cfg else None
                title = await generate_title(
                    user_message,
                    model,
                    max_words=prompts.max_words if prompts else 6,
                    max_chars=prompts.max_chars if prompts else 60,
                )
        except Exception:
            logger.opt(exception=True).warning(
                "后台标题生成失败 conversation={}",
                conversation_id,
            )
        finally:
            await self._persist_title(conversation_id, title)

    async def _persist_title(self, conversation_id: str, title: str | None) -> None:
        """把后台生成的 AI 标题写入 runs 表并清除 ``title_pending``（best-effort）。

        仅覆盖占位标题 —— 由 ``set_title`` 直接写 title 列；回合结束的
        normal persist 路径在 ``existing.title`` 存在时会保留它，因此这里
        写入的 AI 标题不会被回滚。``title`` 为 None（生成失败/模型缺失）时
        只清 pending 标记、保留占位标题。
        """
        try:
            async with SessionLocal() as db:
                if title:
                    await self._run_repo.set_title(db, conversation_id, title)
                await self._run_repo.set_title_pending(db, conversation_id, False)
                await db.commit()
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to persist title for conversation {}",
                conversation_id,
            )

    async def _get_conversation_config(self, conversation_id: str, user_id: int) -> dict[str, Any]:
        """Look up conversation metadata from the runs table, verifying ownership.

        Raises 404 if the conversation does not exist.
        Raises 403 if the conversation belongs to another user.
        """
        async with SessionLocal() as db:
            run = await self._run_repo.get_by_id(db, conversation_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=f"对话 {conversation_id} 不存在，请先调用 POST /conversations 创建",
            )
        if run.user_id is not None and run.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此对话")
        return {"thread_id": run.thread_id}

    @staticmethod
    def _build_message_dict(m: Any) -> dict[str, Any]:
        """Build a message dict, enriching task/subagent tool calls with
        ``is_subagent`` and ``description`` fields extracted from ``tool_input``.
        """
        msg: dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "event_type": m.event_type,
            "tool_name": m.tool_name,
            "tool_input": m.tool_input,
            "tool_output": m.tool_output,
            "file_metadata": m.file_metadata,
            "description": m.description,
            "duration_ms": m.duration_ms,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }

        # Enrich task / subagent tool calls so the frontend can show
        # "委派子代理：生成动态规划脚本" without parsing tool_input JSON.
        if m.tool_name == "task" and m.tool_input:
            msg["is_subagent"] = True
            # Primary: use the dedicated description column (added 2026-07-24).
            if m.description:
                msg["description"] = m.description
            else:
                # Fallback: parse from tool_input JSON for backward compatibility.
                try:
                    parsed = json.loads(m.tool_input)
                    msg["description"] = parsed.get("description", "")
                    msg["subagent_type"] = parsed.get("subagent_type", "general-purpose")
                except Exception:
                    msg["description"] = ""
                    msg["subagent_type"] = "general-purpose"

        return msg
