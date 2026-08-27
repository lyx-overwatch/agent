"""DeferredToolFilterMiddleware — hide deferred tool schemas from the LLM.

When a project uses the SDK's *deferred tool* machinery (MCP
servers that are loaded lazily, ``tool_search`` results, etc.),
the tool registry holds *more* tools than the LLM should see
at once. The active set is sent to the model via
``bind_tools``; the deferred set is held back so the LLM is
not overwhelmed by thousands of MCP tool definitions.

This middleware does two things:

1. In ``wrap_model_call`` it filters the request's
   ``tools`` list — removing the deferred tools before
   langchain binds the tools onto the model.
2. In ``wrap_tool_call`` it intercepts any *attempt* to
   invoke a deferred tool and returns an error
   :class:`ToolMessage` telling the LLM that the tool is
   deferred and must be activated via ``tool_search`` first.

The "what is deferred" decision is **injected**: the
middleware takes a ``deferred_names_provider`` callable that
returns the current set of deferred tool names (or ``None``
if there are no deferred tools). This is the business/feature injection
point — the SDK does not know about the specific
``DeferredToolRegistry`` implementation; the caller passes a
function that returns ``registry.deferred_names`` or
equivalent.

**Brand-neutral**: this middleware is pure infrastructure. It
is part of the SDK's always-on chain, and is a no-op when
no ``deferred_names_provider`` is supplied.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

#: The :class:`ToolMessage` returned when the LLM tries to
#: invoke a deferred tool. Tells the model to use ``tool_search``
#: (or the equivalent discovery mechanism) to activate the tool.
_BLOCKED_TOOL_MSG = (
    "This tool is currently deferred (not active). "
    "Use tool_search to discover and activate it before calling it."
)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    """Hide deferred tool schemas from the model and block deferred tool calls.

    Args:
        deferred_names_provider: A zero-argument callable that
            returns the current set of deferred tool names
            (any iterable of strings). If it returns ``None`` or
            an empty set, the middleware is a no-op. If not
            supplied, the middleware is permanently a no-op.
    """

    def __init__(self, deferred_names_provider: Callable[[], Any] | None = None) -> None:
        super().__init__()
        self._provider = deferred_names_provider

    def _deferred_names(self) -> set[str] | None:
        """Return the current set of deferred tool names, or ``None`` if the provider is missing."""
        if self._provider is None:
            return None
        names = self._provider()
        if not names:
            return None
        return set(names)

    # ------------------------------------------------------------------
    # Model-side filter
    # ------------------------------------------------------------------

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        deferred = self._deferred_names()
        if not deferred:
            return request

        active = [t for t in request.tools if getattr(t, "name", None) not in deferred]

        if len(active) < len(request.tools):
            logger.debug(
                "Filtered %d deferred tool schema(s) from model binding",
                len(request.tools) - len(active),
            )
        return request.override(tools=active)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._filter_tools(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._filter_tools(request))

    # ------------------------------------------------------------------
    # Tool-side block
    # ------------------------------------------------------------------

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage | None:
        """If *request* targets a deferred tool, return a block message; else ``None``."""
        deferred = self._deferred_names()
        if not deferred:
            return None
        name = request.tool_call.get("name")
        if name in deferred:
            tool_call_id = str(request.tool_call.get("id") or "missing_id")
            return ToolMessage(
                content=_BLOCKED_TOOL_MSG,
                tool_call_id=tool_call_id,
                name=str(name) if name else "unknown",
                status="error",
            )
        return None

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)
