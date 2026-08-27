"""Lightweight per-request collector for model-call diagnostics.

This module is the **shared ownership** component for the model-call
capture system.  It lives at the SDK layer so both
:class:`ModelCallCaptureMiddleware` (in ``agent_sdk.middlewares``) and
the SkillHub state logger (in ``app.core.state_logger``) can reference
the same ContextVar-based collector without introducing a dependency
from the SDK into the application layer.

Usage:

1. Middleware pushes summaries: ``collect_model_call(messages)``
2. After the agent run, the caller drains them:
   ``calls = get_model_calls(); reset_model_calls()``
3. The caller passes ``calls`` to its own persistence layer
   (e.g. ``save_state_log(..., model_calls=calls)``).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_MODEL_CALL_COLLECTOR: ContextVar[list[dict[str, Any]]] = ContextVar(
    "_model_call_collector", default=[]
)


def collect_model_call(
    messages: list,
    *,
    estimated_tokens: int = 0,
) -> None:
    """Record a model call during agent execution.

    Called from middleware's ``awrap_model_call``.  Each call appends a
    summary dict to the per-request collector.
    """
    _seq = len(_MODEL_CALL_COLLECTOR.get()) + 1
    preview: list[dict[str, Any]] = []
    for m in messages:
        _type = getattr(m, "type", type(m).__name__)
        _content = getattr(m, "content", "")
        if isinstance(_content, list):
            _content = " ".join(str(c)[:100] for c in _content)
        _content_preview = str(_content)[:200]
        _entry: dict[str, Any] = {
            "type": _type,
            "content_preview": _content_preview,
            "content_length": len(str(_content)),
        }
        if _type == "ai":
            _tc = getattr(m, "tool_calls", None)
            if _tc:
                _entry["tool_calls"] = [
                    {"id": t.get("id", "?"), "name": t.get("name", "?")}
                    for t in _tc
                ]
        if _type == "tool":
            _entry["tool_call_id"] = getattr(m, "tool_call_id", None)
            _entry["name"] = getattr(m, "name", None)
        preview.append(_entry)

    _MODEL_CALL_COLLECTOR.get().append(
        {
            "seq": _seq,
            "message_count": len(messages),
            "estimated_tokens": estimated_tokens,
            "messages": preview,
        }
    )


def get_model_calls() -> list[dict[str, Any]]:
    """Return all collected model call summaries for the current request."""
    return _MODEL_CALL_COLLECTOR.get()


def reset_model_calls() -> None:
    """Reset the model call collector (call after saving state log)."""
    try:
        _MODEL_CALL_COLLECTOR.set([])
    except (ValueError, LookupError):
        pass  # contextvar not set in this context (non-request thread)
