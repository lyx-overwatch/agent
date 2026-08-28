"""Chat SSE streaming endpoints, powered by agent-sdk.

SSE streaming emits structured events so the frontend can show agent
work steps in real time: thinking, tool calls, and token streaming.
"""

import asyncio
import mimetypes
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from starlette.background import BackgroundTask

from app.core.cancel_registry import cancel_registry
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.storage import LocalStorageBackend, get_storage
from app.services.chat import ChatService
from app.utils import PREVIEWABLE_EXTENSIONS, get_model_display_name, get_sse_event

router = APIRouter(prefix="/chat", tags=["chat"])

# SSE 保活心跳间隔（秒）：LLM 重试退避 / 长工具执行期间队列会长时间无事件，
# 若不发任何字节，Next 反代等中间代理可能按 idle timeout 断开连接，前端会误报「网络连接中断」。
_SSE_HEARTBEAT_SECONDS = 15.0


# ── SSE streaming ────────────────────────────────────────────────────────


@router.post("/stream")
async def chat_stream(
    request: Request,
    message: str = Form(...),
    conversation_id: str = Form(...),
    user_id: str = Depends(get_current_user),
    thinking_enabled: bool = Form(True),
    model_name: str | None = Form(None),
    file_metadatas: str | None = Form(None),
    skill_name: str | None = Form(None),
):
    """SSE 流式对话：实时推送 token + 工作步骤事件。

    conversation_id 必须先通过 POST /conversations 创建。
    model_name 可选，不传则使用 config.yaml 的第一个模型。

    客户端断开连接（刷新/关标签页）不会中断后端任务 ——
    任务会继续执行并完整持久化。只有 POST /chat/stream/stop
    才会主动取消。
    """

    async def event_stream():
        svc = ChatService()
        created = int(datetime.now(UTC).timestamp())
        model = get_model_display_name(model_name)
        assistant_message_id = None

        # Register a cancel event for this stream (shared between
        # foreground SSE reader and background agent task).
        cancel_event = cancel_registry.register(conversation_id)

        # ── Background agent task ───────────────────────────────────────
        # The agent runs in its own asyncio Task, pushing events into a
        # queue.  When the client disconnects, the foreground SSE
        # generator is cancelled, but the background task keeps running
        # independently — so the agent always completes and results are
        # always persisted, even after a page refresh.
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def run_agent() -> None:
            """Run the agent in background, feeding events to the queue.

            This task is NOT cancelled when the client disconnects.
            Only POST /chat/stream/stop can cancel it cooperatively
            via the cancel_event.
            """
            try:
                async for evt in svc.execute_stream(
                    message=message,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    thinking_enabled=thinking_enabled,
                    model_name=model_name,
                    file_metadatas=file_metadatas,
                    skill_name=skill_name,
                    cancel_event=cancel_event,
                ):
                    await queue.put(evt)
            except Exception:
                logger.exception(
                    "Background agent task failed for conversation {}",
                    conversation_id,
                )
                # Ensure the foreground sees the failure
                await queue.put({"type": "error", "message": "服务端发生内部错误，本轮生成已中断，请重新发送消息。"})
                await queue.put(
                    {
                        "type": "run_end",
                        "conversation_id": conversation_id,
                        "finish_reason": "error",
                    }
                )
            finally:
                await queue.put(None)  # sentinel — signals end of stream
                cancel_registry.unregister(conversation_id)

        _bg_task = asyncio.ensure_future(run_agent())  # kept alive by event loop

        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_SECONDS)
                except TimeoutError:
                    # 静默期保活：发 SSE 注释行（客户端解析器忽略），仅用于维持连接不被代理断开
                    yield ": keepalive\n\n"
                    continue
                if evt is None:  # sentinel — agent finished
                    break

                evt_type = evt["type"]

                # Capture assistant_message_id from run_start
                if evt_type == "run_start":
                    assistant_message_id = evt["assistant_message_id"]
                    yield get_sse_event(
                        assistant_message_id,
                        "run_start",
                        {
                            "conversation_id": evt["conversation_id"],
                            "thread_id": evt["thread_id"],
                        },
                        created=created,
                        model=model,
                    )
                    continue

                # Resolve message_id (should be set by run_start)
                mid = assistant_message_id or "unknown"

                if evt_type == "thinking_start":
                    yield get_sse_event(mid, "thinking_start", {}, created=created, model=model)
                elif evt_type == "thinking_end":
                    yield get_sse_event(mid, "thinking_end", {}, created=created, model=model)
                elif evt_type == "token":
                    yield get_sse_event(
                        mid,
                        "token",
                        {"content": evt["content"]},
                        created=created,
                        model=model,
                    )
                elif evt_type == "reasoning":
                    yield get_sse_event(
                        mid,
                        "reasoning",
                        {"content": evt["content"]},
                        created=created,
                        model=model,
                    )
                elif evt_type == "tool_start":
                    delta: dict[str, Any] = {
                        "tool": evt["tool"],
                        "input": evt["input"],
                        "run_id": evt.get("run_id", ""),
                    }
                    if evt.get("is_subagent"):
                        delta["is_subagent"] = True
                    if evt.get("description"):
                        delta["description"] = evt["description"]
                    if evt.get("subagent_type"):
                        delta["subagent_type"] = evt["subagent_type"]
                    yield get_sse_event(
                        mid,
                        "tool_start",
                        delta,
                        created=created,
                        model=model,
                    )
                elif evt_type == "tool_end":
                    delta: dict[str, Any] = {
                        "tool": evt["tool"],
                        "output": evt["output"],
                        "run_id": evt.get("run_id", ""),
                    }
                    if evt.get("is_subagent"):
                        delta["is_subagent"] = True
                    if evt.get("error"):
                        delta["error"] = evt["error"]
                    yield get_sse_event(
                        mid,
                        "tool_end",
                        delta,
                        created=created,
                        model=model,
                    )
                elif evt_type == "subagent_progress":
                    yield get_sse_event(
                        mid,
                        "subagent_progress",
                        {
                            "run_id": evt["run_id"],
                            "elapsed_seconds": evt["elapsed_seconds"],
                            "subagent_type": evt["subagent_type"],
                            "description": evt.get("description", ""),
                        },
                        created=created,
                        model=model,
                    )
                elif evt_type == "progress":
                    delta: dict[str, Any] = {
                        "phase": evt["phase"],
                    }
                    if evt.get("tool"):
                        delta["tool"] = evt["tool"]
                    if evt.get("run_id"):
                        delta["run_id"] = evt["run_id"]
                    yield get_sse_event(
                        mid,
                        "progress",
                        delta,
                        created=created,
                        model=model,
                    )
                elif evt_type == "llm_retry":
                    # LLM 重试进度：后端仍在重试、未中断，前端据此显示「正在重试」。
                    yield get_sse_event(
                        mid,
                        "llm_retry",
                        {
                            "attempt": evt.get("attempt"),
                            "max_attempts": evt.get("max_attempts"),
                            "wait_ms": evt.get("wait_ms"),
                            "reason": evt.get("reason"),
                            "message": evt.get("message", ""),
                        },
                        created=created,
                        model=model,
                    )
                elif evt_type == "error":
                    delta: dict[str, Any] = {"message": evt["message"]}
                    if evt.get("recoverable"):
                        delta["recoverable"] = True
                    yield get_sse_event(
                        mid,
                        "error",
                        delta,
                        finish_reason="error",
                        created=created,
                        model=model,
                    )
                elif evt_type == "run_end":
                    yield get_sse_event(
                        mid,
                        "run_end",
                        {"conversation_id": evt["conversation_id"]},
                        finish_reason=evt.get("finish_reason"),
                        created=created,
                        model=model,
                    )

            # Agent completed normally — send DONE marker
            yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            # ── Client disconnected (page refresh / tab close) ────────
            # The foreground SSE generator is cancelled by the ASGI
            # server, but the background agent task is independent and
            # keeps running to completion.  Results will be persisted
            # to the database when the agent finishes.
            logger.info(
                "Client disconnected for conversation {} — agent continues in background",
                conversation_id,
            )
        except Exception:
            # ── Unexpected error in foreground ─────────────────────────
            # The background task is still running — try to notify the
            # client before the connection drops.
            logger.exception(
                "Unhandled exception in SSE stream for conversation {}",
                conversation_id,
            )
            mid = assistant_message_id or "unknown"
            try:
                yield get_sse_event(
                    mid,
                    "error",
                    {"message": "服务端发生内部错误，本轮生成已中断，请重新发送消息。"},
                    finish_reason="error",
                    created=created,
                    model=model,
                )
                yield get_sse_event(
                    mid,
                    "run_end",
                    {"conversation_id": conversation_id},
                    finish_reason="error",
                    created=created,
                    model=model,
                )
            except Exception:
                pass
        # NOTE: no ``finally`` that cancels bg_task or unregisters the
        # cancel event — the background task handles both in its own
        # finally block.

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Stream stop ─────────────────────────────────────────────────────────


@router.post("/stream/stop")
async def stop_stream(
    conversation_id: str = Form(...),
    user_id: str = Depends(get_current_user),
):
    """停止指定对话的流式生成。

    触发合作式取消 —— 正在执行的 agent 循环会在下一次迭代时退出，
    已生成的部分内容会被保存到数据库。
    """
    cancelled = cancel_registry.cancel(conversation_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"对话 {conversation_id} 没有正在进行的流式生成",
        )
    return {"status": "cancelled", "conversation_id": conversation_id}


# ── History ──────────────────────────────────────────────────────────────


@router.get("/messages/{conversation_id}")
async def get_messages(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    """获取指定对话的结构化消息历史（从 messages 表读取，含工具调用记录）。"""
    svc = ChatService()
    return await svc.get_messages(conversation_id, user_id)


# ── File serving ──────────────────────────────────────────────────────────


@router.get("/files/{conversation_id}")
async def serve_file(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
    path: str = Query(..., description="Virtual file path, e.g. /mnt/user-data/outputs/report.pptx"),
    download: bool = Query(False, description="Force download as attachment"),
):
    """Serve a file from the agent's workspace/outputs/uploads directories.

    Local storage: returns the file directly via FileResponse.
    S3 storage: streams the object through Heyu Agent (proxied) so the browser
    stays on the same origin — OBS's endpoint is internal and not CORS-enabled,
    so a 302 to the pre-signed URL would be blocked by the browser.
    """
    svc = ChatService()
    thread_id = await svc._get_thread_id(conversation_id, user_id)

    storage = get_storage()

    # ── S3/remote storage: proxy bytes through Heyu Agent ─────────────────
    # Do NOT 302-redirect to the OBS pre-signed URL: OBS's endpoint is an
    # internal address with no CORS headers, so a browser ``fetch`` following
    # the redirect would be blocked. Stream the object server-side instead so
    # download/preview stays on the same origin as the frontend.
    if not isinstance(storage, LocalStorageBackend):
        try:
            storage_key = svc.virtual_path_to_storage_key(path, thread_id, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if not await storage.exists(storage_key):
            raise HTTPException(status_code=404, detail=f"File not found in storage: {path}")

        filename = storage_key.rsplit("/", 1)[-1]
        media_type, _ = mimetypes.guess_type(filename)
        if media_type is None:
            media_type = "application/octet-stream"

        safe_name = filename
        try:
            safe_name.encode("ascii")
        except UnicodeEncodeError:
            safe_name = f"UTF-8''{quote(filename)}"

        disposition = "attachment" if download else "inline"
        headers = {"Content-Disposition": f'{disposition}; filename="{safe_name}"'}

        return StreamingResponse(storage.download_stream(storage_key), media_type=media_type, headers=headers)

    # ── Local storage: serve from disk ─────────────────────────────────
    try:
        physical = svc.resolve_file_path(path, thread_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not physical.exists() or not physical.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {physical.name}")

    media_type, _ = mimetypes.guess_type(str(physical))
    if media_type is None:
        media_type = "application/octet-stream"

    safe_filename = physical.name
    try:
        safe_filename.encode("ascii")
    except UnicodeEncodeError:
        safe_filename = f"UTF-8''{quote(physical.name)}"

    headers: dict[str, str] = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
    else:
        headers["Content-Disposition"] = f'inline; filename="{safe_filename}"'

    return FileResponse(path=str(physical), media_type=media_type, headers=headers)


@router.get("/files/{conversation_id}/url")
async def file_download_url(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
    path: str = Query(..., description="Virtual file path"),
    download: bool = Query(False, description="Generate an attachment (download) URL"),
):
    """Return a self-authenticating URL for the file (Java-style download).

    For S3/OBS this is the pre-signed URL — the browser navigates to it
    directly, so no CORS and no ``Authorization`` header are needed (the
    signature in the query string authenticates the request). For local
    storage it returns the same-origin serve path.
    """
    svc = ChatService()
    thread_id = await svc._get_thread_id(conversation_id, user_id)

    storage = get_storage()

    # ── Local storage: same-origin serve path ───────────────────────────
    if isinstance(storage, LocalStorageBackend):
        url = f"/py/api/chat/files/{conversation_id}?path={quote(path)}"
        if download:
            url += "&download=true"
        return {"url": url, "backend": "local"}

    # ── S3/OBS: pre-signed URL ──────────────────────────────────────────
    try:
        storage_key = svc.virtual_path_to_storage_key(path, thread_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not await storage.exists(storage_key):
        raise HTTPException(status_code=404, detail=f"File not found in storage: {path}")

    response_content_disposition = ""
    if download:
        safe_name = storage_key.rsplit("/", 1)[-1]
        try:
            safe_name.encode("ascii")
        except UnicodeEncodeError:
            safe_name = f"UTF-8''{quote(safe_name)}"
        response_content_disposition = f'attachment; filename="{safe_name}"'

    url = await storage.download_url(
        storage_key,
        expires_in=settings.download_url_expires,
        response_content_disposition=response_content_disposition,
    )
    return {"url": url, "backend": "s3"}


@router.get("/files/{conversation_id}/info")
async def file_info(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
    path: str = Query(..., description="Virtual file path"),
):
    """Return metadata for a file so the frontend can decide whether to preview it."""
    svc = ChatService()
    thread_id = await svc._get_thread_id(conversation_id, user_id)

    storage = get_storage()

    # ── S3 storage: get metadata from object store ──────────────────────
    if not isinstance(storage, LocalStorageBackend):
        try:
            storage_key = svc.virtual_path_to_storage_key(path, thread_id, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            metadata = await storage.get_metadata(storage_key)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"File not found in storage: {path}")

        # S3's get_metadata only returns {size, content_type, last_modified} —
        # the frontend preview also needs filename/extension/previewable, so
        # derive them from the object key to match the local-storage shape.
        filename = storage_key.rsplit("/", 1)[-1]
        extension = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
        return {
            **metadata,
            "filename": filename,
            "extension": extension,
            "previewable": extension in PREVIEWABLE_EXTENSIONS,
        }

    # ── Local storage ──────────────────────────────────────────────────
    try:
        return svc.get_file_info(path, thread_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/files/{conversation_id}/download-dir")
async def download_directory(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
    path: str = Query(..., description="Virtual directory path, e.g. /mnt/user-data/outputs/subdir/"),
):
    """打包下载整个目录为 zip。

    S3 存储下逐对象流式打包（内存占用受 chunk 限制），大目录不会占满内存；
    打包结果落盘后经 FileResponse 流式返回给前端，响应结束后清理临时文件。
    """
    svc = ChatService()
    result = await svc.download_directory(conversation_id, path, user_id=user_id)
    tmp_path = result["tmp_path"]
    filename = result["filename"]
    return FileResponse(
        path=tmp_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_remove_tmp_file, tmp_path),
    )


def _remove_tmp_file(path: str) -> None:
    """清理目录打包产生的临时 zip 文件。"""
    try:
        os.unlink(path)
    except OSError:
        pass
