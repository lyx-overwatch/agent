"""Stream event handler — translate LangGraph raw events into structured stream events.

Encapsulates the main agent event loop with subagent progress tracking,
cancellation polling, step collection, and error classification.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from agent_sdk.community.skillhub import CANCEL_EVENT_CTX
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from loguru import logger

from app.core.cancel_registry import cancel_registry

# ── Truncation limits ────────────────────────────────────────────────────
_TOOL_OUTPUT_MAX_CHARS = 2000
_TOOL_INPUT_MAX_CHARS = 500


def _truncate(val: str, max_chars: int) -> str:
    """Truncate *val* to *max_chars*, appending a summary suffix if needed."""
    if len(val) <= max_chars:
        return val
    return val[:max_chars] + f"... (truncated, {len(val)} total chars)"


def _extract_reasoning(chunk: Any) -> str | None:
    """Extract reasoning / thinking content from a streaming chunk."""
    ak = getattr(chunk, "additional_kwargs", {}) or {}
    if "reasoning_content" in ak:
        return ak["reasoning_content"]
    if "thinking" in ak:
        return ak["thinking"]
    return None


def _serialise_tool_input(input_val: Any) -> str:
    """Serialise a tool input value to a truncated string."""
    try:
        if isinstance(input_val, str):
            return _truncate(input_val, _TOOL_INPUT_MAX_CHARS)
        return _truncate(json.dumps(input_val, ensure_ascii=False, default=str), _TOOL_INPUT_MAX_CHARS)
    except Exception:
        return str(input_val)[:_TOOL_INPUT_MAX_CHARS]


def _collect_step(event: dict, steps: list) -> None:
    """Append a step entry to *steps* based on the raw LangGraph event."""
    kind = event["event"]
    if kind == "on_tool_start":
        tool_name = event.get("name", "unknown")
        tool_input = event["data"].get("input", {})
        run_id = event.get("run_id") or f"tc_{uuid.uuid4().hex[:8]}"
        step: dict[str, Any] = {
            "type": "tool_start",
            "tool": tool_name,
            "input": _serialise_tool_input(tool_input),
            "run_id": run_id,
        }
        if tool_name == "task":
            step["is_subagent"] = True
            if isinstance(tool_input, dict):
                step["description"] = tool_input.get("description", "")
        steps.append(step)
    elif kind == "on_tool_end":
        tool_name = event.get("name", "unknown")
        raw = event["data"].get("output", "")
        step = {
            "type": "tool_end",
            "tool": tool_name,
            "output": _truncate(str(raw), _TOOL_OUTPUT_MAX_CHARS),
        }
        if tool_name == "task":
            step["is_subagent"] = True
        steps.append(step)
    elif kind == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        reasoning = _extract_reasoning(chunk)
        if reasoning:
            if steps and steps[-1]["type"] == "reasoning":
                if reasoning.startswith(steps[-1]["content"]):
                    steps[-1]["content"] = reasoning
                else:
                    steps[-1]["content"] += reasoning
            else:
                steps.append({"type": "reasoning", "content": reasoning})
        if chunk.content:
            if steps and steps[-1]["type"] == "thinking":
                steps[-1]["content"] += chunk.content
            else:
                steps.append({"type": "thinking", "content": chunk.content})


async def _cancel_and_drain(task: asyncio.Task | None, *, timeout: float = 0.2) -> None:
    """Cancel *task* and await it, bounded by *timeout*.

    Cancelling ``astream_events.__anext__()`` does not always return
    promptly: its ``finally`` awaits the underlying graph task, which —
    when the agent is mid-subagent-delegation — may itself be waiting on
    a subagent thread that does not observe the cancellation.  Blocking on
    that await is exactly what made "stop generation" feel stuck.  Bound
    the wait to a short timeout so the stream ends immediately; the
    already-cancelled graph task finishes unwinding in the background.
    The cancelled path no longer reads the checkpoint or syncs files, so
    there is no dependency on the graph having fully unwound.
    """
    if task is None or task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (asyncio.CancelledError, StopAsyncIteration, TimeoutError):
        pass


class StreamEventHandler:
    """Process raw LangGraph astream_events and yield structured stream events.

    Usage::

        handler = StreamEventHandler(
            agent=agent,
            conversation_id=conversation_id,
            cancel_event=cancel_event,
        )
        async for evt in handler.process(human_msg, config):
            yield evt

        # After the loop, read accumulated state:
        if handler.error:
            ...
        if handler.cancelled:
            ...
    """

    def __init__(
        self,
        agent: Any,
        conversation_id: str,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self._agent = agent
        self._conversation_id = conversation_id
        self._cancel_event = cancel_event

        # Accumulated state — populated during process()
        self.steps: list[dict[str, Any]] = []
        self.all_tokens: list[str] = []
        self.error: Exception | None = None
        self.error_message: str | None = None
        # True when the run ended due to a *recoverable* interruption
        # (e.g. step/recursion limit) — the checkpoint is preserved and the
        # user can simply continue the conversation.  Surfaced to the
        # frontend so it renders a hint instead of a hard error.
        self.recoverable: bool = False
        self.cancelled: bool = False

        # Cancel token for context-var management (caller must reset it)
        self._cancel_token: Any = None

        # ── Progress-tracking state (heartbeat events) ─────────────────
        # Non-subagent tools currently running: run_id → (start, name).
        self._active_tools: dict[str, tuple[float, str]] = {}

    @property
    def cancel_token(self) -> Any:
        """The context-var token set during :meth:`process`.

        The caller must reset this via ``CANCEL_EVENT_CTX.reset(token)``
        in a ``finally`` block after the stream completes.
        """
        return self._cancel_token

    async def process(
        self,
        human_msg: HumanMessage,
        config: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run the agent event loop and yield structured stream events.

        Args:
            human_msg: The user's ``HumanMessage`` to send to the agent.
            config: LangGraph runnable config (must include ``thread_id``).

        Yields:
            Dicts with keys ``type`` — one of ``thinking_start``,
            ``token``, ``reasoning``, ``thinking_end``, ``tool_start``,
            ``tool_end``, ``subagent_progress``, ``progress``, ``error``.
        """
        # ── Propagate cancellation token to synchronous subagent code ──
        if self._cancel_event is not None:
            _thread_evt = cancel_registry.get_thread_event(self._conversation_id)
            if _thread_evt is not None:
                self._cancel_token = CANCEL_EVENT_CTX.set(_thread_evt)

        import time as _time  # noqa: PLC0415

        _active_subagents: dict[str, tuple[float, str, str]] = {}
        _stream = self._agent.astream_events(
            {"messages": [human_msg]},
            config=config,
            version="v2",
        )
        _next_event_task: asyncio.Task | None = None

        try:
            while True:
                # Cooperative cancellation — poll on EVERY iteration, not
                # just when the stream goes quiet.  During rapid token
                # streaming ``__anext__()`` returns in milliseconds, so the
                # 1s timer below never fires and a stop request would
                # otherwise go unnoticed until the model finishes its
                # current response.
                if self._cancel_event is not None and self._cancel_event.is_set():
                    await _cancel_and_drain(_next_event_task)
                    self.cancelled = True
                    logger.info(
                        "Stream cancelled for conversation {}",
                        self._conversation_id,
                    )
                    break

                # Lazily create the next-event task so we never
                # cancel it — on timeout we keep it alive for the
                # next iteration.
                if _next_event_task is None:
                    _next_event_task = asyncio.ensure_future(_stream.__anext__())

                _timer = asyncio.ensure_future(asyncio.sleep(1.0))
                # Wait on the next event, the 1s heartbeat, AND — so a
                # "stop" request is honoured immediately even while a
                # subagent is running — the cancel event itself.  Without
                # this third awaitable the loop only re-checks the cancel
                # flag on the 1s heartbeat, adding up to a full second of
                # perceived lag when the stream is quiet mid-delegation.
                _waitables = [_next_event_task, _timer]
                _cancel_waiter = None
                if self._cancel_event is not None:
                    _cancel_waiter = asyncio.ensure_future(self._cancel_event.wait())
                    _waitables.append(_cancel_waiter)

                _done, _pending = await asyncio.wait(
                    _waitables,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Reap the futures we won't consume (keep _next_event_task
                # alive across iterations so a timeout never cancels an
                # in-flight read).
                if _cancel_waiter is not None and not _cancel_waiter.done():
                    _cancel_waiter.cancel()
                if not _timer.done():
                    _timer.cancel()

                # Cancel event fired while we were waiting → stop now.
                if self._cancel_event is not None and self._cancel_event.is_set():
                    await _cancel_and_drain(_next_event_task)
                    self.cancelled = True
                    logger.info(
                        "Stream cancelled for conversation {}",
                        self._conversation_id,
                    )
                    break

                if _timer in _done:
                    # Timeout — the timer completed but the stream
                    # hasn't produced the next event yet.  Do NOT
                    # cancel _next_event_task — it stays alive for
                    # the next poll iteration.
                    _timer.result()  # drain (no exception expected)
                    _now = _time.monotonic()
                    # Emit progress for each active subagent.
                    if _active_subagents:
                        for _rid, (_start, _sa_type, _desc) in _active_subagents.items():
                            yield {
                                "type": "subagent_progress",
                                "run_id": _rid,
                                "elapsed_seconds": round(_now - _start, 1),
                                "subagent_type": _sa_type,
                                "description": _desc,
                            }
                    # Emit progress for the active non-subagent tool
                    # (covers slow tools).
                    elif self._active_tools:
                        for _rid, (_start, _tool) in self._active_tools.items():
                            yield {
                                "type": "progress",
                                "phase": "tool",
                                "tool": _tool,
                                "run_id": _rid,
                            }
                    # No tool running — the model is thinking (or the
                    # graph is still producing its first event).  A generic
                    # "generating" heartbeat keeps the frontend animated.
                    else:
                        # 思考中不携带耗时 —— 前端只对「子代理委派」展示耗时。
                        yield {
                            "type": "progress",
                            "phase": "thinking",
                        }
                    continue

                # Event received — cancel the timer and consume the event.
                _timer.cancel()
                try:
                    event = _next_event_task.result()
                except StopAsyncIteration:
                    break
                finally:
                    _next_event_task = None

                kind = event["event"]

                if "middleware:summarize" in event.get("tags", []):
                    continue

                if kind == "on_chat_model_start":
                    yield {"type": "thinking_start"}

                elif kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        self.all_tokens.append(chunk.content)
                        yield {"type": "token", "content": chunk.content}
                    reasoning = _extract_reasoning(chunk)
                    if reasoning:
                        yield {"type": "reasoning", "content": reasoning}

                elif kind == "on_chat_model_end":
                    # LangGraph may attach structured error info to the
                    # model end event when the LLM call fails (e.g. 400
                    # BadRequestError).  We log it but do NOT yield an
                    # error event here — the post-hoc scan detects
                    # AIMessage errors reliably.
                    _output = event["data"].get("output", {})
                    _model_err = None
                    if isinstance(_output, dict):
                        _model_err = _output.get("error")
                    if _model_err:
                        logger.warning(
                            "Model end with error for conversation {}: {}",
                            self._conversation_id,
                            str(_model_err)[:500],
                        )
                    yield {"type": "thinking_end"}

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_input = event["data"].get("input", {})
                    run_id = event.get("run_id") or f"tc_{uuid.uuid4().hex[:8]}"
                    evt: dict[str, Any] = {
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": _serialise_tool_input(tool_input),
                        "run_id": run_id,
                    }
                    if tool_name == "task":
                        evt["is_subagent"] = True
                        if isinstance(tool_input, dict):
                            desc = tool_input.get("description", "")
                            sa_type = tool_input.get("subagent_type", "general-purpose")
                            evt["description"] = desc
                            evt["subagent_type"] = sa_type
                            # Start tracking for progress events
                            _active_subagents[run_id] = (_time.monotonic(), sa_type, desc)
                    else:
                        # Track non-subagent tools for heartbeat progress.
                        self._active_tools[run_id] = (_time.monotonic(), tool_name)
                    yield evt

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    raw_output = event["data"].get("output", "")
                    tool_output = _truncate(str(raw_output), _TOOL_OUTPUT_MAX_CHARS)
                    run_id = event.get("run_id") or ""
                    # ── Detect tool errors ──────────────────────────────
                    _tool_err = event["data"].get("error")
                    evt: dict[str, Any] = {
                        "type": "tool_end",
                        "tool": tool_name,
                        "output": tool_output,
                        "run_id": run_id,
                    }
                    if _tool_err:
                        evt["error"] = str(_tool_err)[:500]
                        logger.warning(
                            "Tool end with error for conversation {} (tool={}): {}",
                            self._conversation_id,
                            tool_name,
                            str(_tool_err)[:300],
                        )
                    if tool_name == "task":
                        evt["is_subagent"] = True
                        # Pop tracking — subagent is done
                        if run_id in _active_subagents:
                            _start, _, _ = _active_subagents.pop(run_id)
                            evt["elapsed_seconds"] = round(_time.monotonic() - _start, 1)
                    else:
                        # Pop tracking — non-subagent tool is done.
                        self._active_tools.pop(run_id, None)
                    yield evt

                elif kind == "on_chain_end":
                    # ── Detect chain-level errors ───────────────────────
                    _chain_output = event["data"].get("output", {})
                    _chain_err = event["data"].get("error")
                    if _chain_err or (isinstance(_chain_output, dict) and _chain_output.get("error")):
                        _err_msg = str(_chain_err or _chain_output.get("error", ""))
                        logger.warning(
                            "Chain end with error for conversation {} (name={}): {}",
                            self._conversation_id,
                            event.get("name", "?"),
                            _err_msg[:500],
                        )
                        _friendly = "Agent 执行链路发生内部错误，请重试。"
                        _msg_match = re.search(r"message_zh['\"]?\s*:\s*['\"]([^'\"]+)", _err_msg)
                        if not _msg_match:
                            _msg_match = re.search(r"'message'\s*:\s*'([^']+)", _err_msg)
                        if _msg_match:
                            _friendly = _msg_match.group(1)
                        self.error = RuntimeError(_friendly)
                        yield {"type": "error", "message": _friendly}

                else:
                    # ── Diagnostic: log unhandled event kinds ──────────
                    _name = event.get("name", "")
                    logger.debug(
                        "Unhandled event kind {!r} (name={!r}) for conversation {}",
                        kind,
                        _name,
                        self._conversation_id,
                    )

                _collect_step(event, self.steps)

                # ── Persist subagent elapsed time to DB ─────────────────
                # ``_collect_step`` works from raw LangGraph events,
                # which don't carry elapsed_seconds.  Inject the value
                # into the last step so ``_save_chat_to_db`` can store
                # it as ``duration_ms``.
                if kind == "on_tool_end" and event.get("name") == "task" and self.steps:
                    _elapsed = evt.get("elapsed_seconds")
                    if _elapsed is not None:
                        self.steps[-1]["duration_ms"] = int(_elapsed * 1000)

        except asyncio.CancelledError:
            # Generator task cancelled by the ASGI server (e.g. client
            # disconnect).  Treat as a soft cancellation — persist
            # partial results so nothing is lost.
            logger.info(
                "Stream generator cancelled for conversation {}, will persist partial results",
                self._conversation_id,
            )
            self.cancelled = True
            # ── Clean up pending event task ────────────────────────────
            await _cancel_and_drain(_next_event_task)
            # Close the agent stream so LangGraph cleans up internal
            # resources (pipelines, connections).  Guard with a
            # timeout so a stuck cleanup cannot block persistence.
            try:
                await asyncio.wait_for(_stream.aclose(), timeout=5.0)
            except Exception:
                pass
        except GraphRecursionError:
            logger.exception(
                "Agent recursion limit exceeded for conversation {}",
                self._conversation_id,
            )
            self.error_message = "任务较复杂，已达到单次执行的步骤上限，Agent 已自动暂停。你可以继续追问（例如「请继续」），Agent 会接着上次的进度继续生成。"
            self.error = GraphRecursionError(self.error_message)
            self.recoverable = True
            yield {"type": "error", "message": self.error_message, "recoverable": True}
        except Exception as exc:
            logger.exception(
                "Error during agent streaming for conversation {}",
                self._conversation_id,
            )
            self.error = exc
            # Try to extract a user-friendly message from the exception.
            _err_msg = str(exc)
            _msg_match = re.search(r"message_zh['\"]?\s*:\s*['\"]([^'\"]+)", _err_msg)
            if not _msg_match:
                _msg_match = re.search(r"'message'\s*:\s*'([^']+)", _err_msg)
            if _msg_match:
                self.error_message = _msg_match.group(1)
            else:
                self.error_message = "Agent 执行过程中发生内部错误，请重试。"
            yield {"type": "error", "message": self.error_message}
