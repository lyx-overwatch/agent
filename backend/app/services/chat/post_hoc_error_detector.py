"""Post-hoc error detector — scan agent state after execution for hidden errors.

When LangGraph catches API errors (BadRequestError, etc.) internally, they never
reach the stream exception handler.  But the agent state may contain error
ToolMessages or empty final responses.  This module scans the state to detect
these after execution completes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class PostHocResult:
    """Result of post-hoc error detection on agent state messages."""

    detected_errors: list[str] = field(default_factory=list)
    """Raw error descriptions found in the message state."""

    clarification_texts: list[str] = field(default_factory=list)
    """Clarification question texts to yield to the frontend."""

    last_ai_content: str = ""
    """Content of the last AIMessage in the new messages."""

    last_ai_has_tool_calls: bool = False
    """Whether the last AIMessage had pending tool calls."""

    fatal_error: Exception | None = None
    """Set when the error should be reported to the frontend (not recoverable)."""

    error_message: str | None = None
    """Frontend-visible error text (extracted from the raw error)."""


class PostHocErrorDetector:
    """Scan agent state messages after execution to detect hidden errors.

    Usage::

        result = PostHocErrorDetector.detect(
            state_after=state_after,
            state_before=state_before,
            cancelled=False,
            conversation_id=conversation_id,
        )
        if result.clarification_texts:
            for text in result.clarification_texts:
                yield {"type": "token", "content": text}
        if result.fatal_error:
            yield {"type": "error", "message": result.error_message}
    """

    @staticmethod
    def detect(
        state_after: dict[str, Any] | None,
        state_before: dict[str, Any] | None,
        cancelled: bool,
        conversation_id: str,
    ) -> PostHocResult:
        """Scan *state_after* messages for errors that LangGraph caught internally.

        Args:
            state_after: Agent state snapshot after the run.
            state_before: Agent state snapshot before the run (used to scope
                analysis to only new messages).
            cancelled: Whether the run was explicitly cancelled — empty/partial
                responses are expected and should not be flagged.
            conversation_id: Used for log messages only.

        Returns:
            A :class:`PostHocResult` with detected errors, clarification texts,
            and a fatal_error if one should be reported to the frontend.
        """
        result = PostHocResult()

        if state_after is None or cancelled:
            return result

        _msgs = state_after.get("messages", [])
        # Only scan messages added during THIS run to avoid re-reporting
        # errors from previous failed attempts that remain in checkpoint state.
        if state_before is not None:
            _prev_count = len(state_before.get("messages", []))
        else:
            _prev_count = 0
            logger.warning(
                "state_before not captured for conversation {} — "
                "post-hoc error detection will scan all {} messages; "
                "stale errors from previous runs may be falsely reported",
                conversation_id, len(_msgs),
            )
        _new_msgs = _msgs[_prev_count:]

        _detected_errors: list[str] = []
        _last_ai_content = ""
        _last_ai_has_tool_calls = False
        _clarification_texts: list[str] = []

        # Diagnostic: dump the last 3 messages for forensics
        for _i, _msg in enumerate(_msgs[-3:]):
            _cls = type(_msg).__name__
            _content = getattr(_msg, "content", "") or ""
            if isinstance(_content, list):
                _content = " ".join(str(c)[:200] for c in _content)
            _content_str = str(_content)[:300]
            _tool_call_id = getattr(_msg, "tool_call_id", None)
            _name = getattr(_msg, "name", "")
            _status = getattr(_msg, "status", "")
            logger.debug(
                "Post-hoc msg[{}/{}] type={} name={} status={} tool_call_id={} content={}",
                len(_msgs) - 3 + _i + 1, len(_msgs),
                _cls, _name, _status, _tool_call_id,
                _content_str[:200],
            )

        for _msg in _new_msgs:
            _cls = type(_msg).__name__
            _content = getattr(_msg, "content", "") or ""
            if isinstance(_content, list):
                _content = " ".join(str(c) for c in _content)
            _content_str = str(_content)

            # Track the last AIMessage content to detect empty responses
            if _cls == "AIMessage":
                _last_ai_content = _content_str
                _tc = getattr(_msg, "tool_calls", None)
                _last_ai_has_tool_calls = bool(_tc)

            # ── AIMessage with error content ───────────────────────────
            # When the LLM API call fails with 400, LangGraph catches
            # the error and creates an AIMessage with content like
            # "LLM request failed: BadRequestError: ...".  These are
            # never streamed (no on_chat_model_stream events), so we
            # must detect them post-hoc.
            if _cls == "AIMessage" and _content_str:
                _lc = _content_str.lower()
                _ai_err_markers = [
                    "llm request failed",
                    "badrequesterror",
                    "permissiondeniederror",
                    "error code: 400",
                    "error code: 403",
                    "tool call result does not follow",
                    "invalid_request_error",
                ]
                if any(m in _lc for m in _ai_err_markers):
                    _detected_errors.append(
                        f"AIMessage API error: {_content_str[:500]}"
                    )

            # ToolMessage with error content from the LLM API.
            if _cls == "ToolMessage" and _content_str:
                _status = getattr(_msg, "status", "")
                _lc = _content_str.lower()
                _api_err_markers = [
                    "badrequesterror",
                    "permissiondeniederror",
                    "tool call result does not follow tool call",
                    "error code: 400",
                    "error code: 403",
                    "invalid_request_error",
                ]
                if _status == "error" or any(m in _lc for m in _api_err_markers):
                    _detected_errors.append(
                        f"ToolMessage error (name={getattr(_msg, 'name', '?')}, "
                        f"status={_status}): {_content_str[:300]}"
                    )

                # ── Collect clarification messages ─────────────────────
                # ClarificationMiddleware intercepts ask_clarification
                # tool calls and adds a ToolMessage to the state, but
                # no on_tool_start / on_tool_end stream events are
                # emitted.  Collect them here so they can be yielded
                # to the frontend post-hoc.
                if getattr(_msg, "name", "") == "ask_clarification":
                    _clarification_texts.append(_content_str)

        result.last_ai_content = _last_ai_content
        result.last_ai_has_tool_calls = _last_ai_has_tool_calls
        result.clarification_texts = _clarification_texts

        # Also detect if the agent produced no meaningful response
        # (empty AIMessage — the model call likely failed)
        if not _detected_errors and not _last_ai_content.strip() and not _last_ai_has_tool_calls:
            result.fatal_error = RuntimeError(
                "Agent produced empty response — the model call may have failed "
                "with an API error (e.g. BadRequestError 400) that was caught "
                "by LangGraph internally."
            )
            result.error_message = "Agent 执行过程中发生内部错误，本轮已中断，请重新发送消息。"
            logger.warning(
                "Post-hoc: agent produced empty AIMessage for conversation {} "
                "({} total messages)",
                conversation_id, len(_msgs),
            )
            return result

        if _detected_errors:
            # ── Classify errors: API-level vs tool-level ──────────────
            _ai_errors = [e for e in _detected_errors if e.startswith("AIMessage")]
            _tool_errors = [e for e in _detected_errors if e.startswith("ToolMessage")]

            # When the agent produced a meaningful final response
            # (or its last action was issuing tool calls — still
            # working) and there are only tool-level errors, the
            # agent recovered / is recovering successfully.  Log
            # a warning for forensics but do NOT report an error
            # to the frontend.
            if not _ai_errors and (_last_ai_content.strip() or _last_ai_has_tool_calls):
                logger.warning(
                    "Post-hoc: {} recoverable tool error(s) for conversation {} "
                    "(agent produced final response, not reporting to frontend): {}",
                    len(_tool_errors), conversation_id,
                    "; ".join(e[:300] for e in _tool_errors),
                )
            else:
                # Fatal error — either an API-level failure or no
                # final response was produced.  Report to frontend.
                _raw = _detected_errors[0]
                _friendly = _raw
                _msg_match = re.search(r"message_zh['\"]?\s*:\s*['\"]([^'\"]+)", _raw)
                if not _msg_match:
                    _msg_match = re.search(r"'message'\s*:\s*'([^']+)", _raw)
                if _msg_match:
                    _friendly = _msg_match.group(1)
                elif "tool call result does not follow tool call" in _raw:
                    _friendly = "工具调用结果与待处理的工具调用不匹配，对话历史可能已损坏。请开启新对话重试。"
                else:
                    # Non-API tool error (e.g. web_fetch ConnectTimeout).
                    # Strip the verbose prefix so only the tool's own
                    # (already-sanitized) message reaches the frontend.
                    _friendly = re.sub(
                        r'^ToolMessage error \([^)]+\):\s*', '', _raw
                    ).strip()
                result.fatal_error = RuntimeError(_friendly)
                result.error_message = _friendly
                result.detected_errors = _detected_errors
                logger.warning(
                    "Post-hoc error detection for conversation {}: {} error(s) found in {} new messages (total state: {})",
                    conversation_id, len(_detected_errors), len(_new_msgs), len(_msgs),
                )

        return result
