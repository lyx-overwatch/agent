"""ToolErrorHandlingMiddleware — convert tool exceptions into error ToolMessages.

By default, if a tool raises an exception, langgraph's tool
node bubbles the exception up the stack and crashes the run.
This middleware sits in front of the tool node and catches
every exception, replacing it with an :class:`ToolMessage`
whose ``status="error"`` and whose content describes the
failure. The agent loop can then continue gracefully —
typically the LLM will see the error, adjust, and call a
different tool.

LangGraph control-flow signals (``GraphBubbleUp`` —
``interrupt`` / ``pause`` / ``resume``) are preserved: they
re-raise as-is so the graph runtime can do the right thing.

The error message format is:

    Error: Tool '<name>' failed with <ExcClass>: <detail truncated to 500 chars>.
    Continue with available context, or choose an alternative tool.

**Brand-neutral**: this middleware is pure infrastructure. It
is part of the SDK's always-on chain.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"
_MAX_ERROR_DETAIL_LEN = 500


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Catch tool exceptions and return error :class:`ToolMessage`\\ s instead.

    The middleware wraps both the sync (``wrap_tool_call``) and
    async (``awrap_tool_call``) tool-call hooks. If the
    downstream handler raises an exception, the middleware
    builds an error :class:`ToolMessage` and returns it in
    place of the exception. ``GraphBubbleUp`` (used by
    langgraph for ``interrupt``/``pause``/``resume``) is
    re-raised so the graph runtime can react to control-flow
    signals.
    """

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > _MAX_ERROR_DETAIL_LEN:
            detail = detail[: _MAX_ERROR_DETAIL_LEN - 3] + "..."

        content = (
            f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. "
            f"Continue with available context, or choose an alternative tool."
        )
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals.
            raise
        except Exception as exc:
            logger.exception(
                "Tool execution failed (sync): name=%s id=%s",
                request.tool_call.get("name"),
                request.tool_call.get("id"),
            )
            return self._build_error_message(request, exc)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            logger.exception(
                "Tool execution failed (async): name=%s id=%s",
                request.tool_call.get("name"),
                request.tool_call.get("id"),
            )
            return self._build_error_message(request, exc)
