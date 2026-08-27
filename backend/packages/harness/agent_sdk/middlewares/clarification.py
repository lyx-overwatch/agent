"""ClarificationMiddleware — intercept ask_clarification tool calls.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.clarification_middleware``.

When the model calls the ``ask_clarification`` tool, this
middleware short-circuits the normal tool execution and
returns a :class:`Command` that:

* adds a formatted ``ToolMessage`` to the message history
  (so the frontend can render the question); and
* jumps to ``END`` to pause execution until the user
  responds.

The tool name is configurable so a product that uses a
different tool name can wire the middleware in without
forking. The format is brand-neutral (icons + numbered
options), with a small Chinese-character detector used to
pick the appropriate icon.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from hashlib import sha256
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


#: Default tool name to watch for. Matches the factory in
#: :mod:`agent_sdk.tools.factory` and the contract in
#: :mod:`agent_sdk.tools.ask_clarification`.
DEFAULT_CLARIFICATION_TOOL_NAME: str = "ask_clarification"

#: Map of clarification_type → emoji icon. Brand-neutral
#: (no specific brand), but covers the common types the
#: reference model uses.
_TYPE_ICONS: dict[str, str] = {
    "missing_info": "❓",
    "ambiguous_requirement": "🤔",
    "approach_choice": "🔀",
    "risk_confirmation": "⚠️",
    "suggestion": "💡",
}


class ClarificationMiddlewareState(AgentState):
    """Compatible with the :class:`ThreadState` schema."""


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Interrupt execution when the model asks the user a clarification question.

    Args:
        tool_name: Tool name to intercept (default:
            :data:`DEFAULT_CLARIFICATION_TOOL_NAME`).
    """

    state_schema = ClarificationMiddlewareState

    def __init__(self, tool_name: str = DEFAULT_CLARIFICATION_TOOL_NAME) -> None:
        super().__init__()
        self._tool_name = tool_name

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        """Deterministic id so a retried clarification call replaces, not appends."""
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    # ------------------------------------------------------------------
    # Message rendering
    # ------------------------------------------------------------------

    def _is_chinese(self, text: str) -> bool:
        return any("一" <= ch <= "鿿" for ch in text)

    def _format_clarification_message(self, args: dict) -> str:
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        # Some models serialize arrays as JSON strings — normalise.
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]
        if options is None:
            options = []
        elif not isinstance(options, list):
            options = [options]

        icon = _TYPE_ICONS.get(clarification_type, "❓")

        parts: list[str] = []
        if context:
            parts.append(f"{icon} {context}")
            parts.append(f"\n{question}")
        else:
            parts.append(f"{icon} {question}")

        if options:
            parts.append("")
            for i, opt in enumerate(options, 1):
                parts.append(f"  {i}. {opt}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Intercept handler
    # ------------------------------------------------------------------

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        args = request.tool_call.get("args", {})
        formatted = self._format_clarification_message(args)
        tool_call_id = request.tool_call.get("id", "")

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", args.get("question", ""))

        tool_message = ToolMessage(
            id=self._stable_message_id(tool_call_id, formatted),
            content=formatted,
            tool_call_id=tool_call_id,
            name=self._tool_name,
        )
        return Command(update={"messages": [tool_message]}, goto=END)

    # ------------------------------------------------------------------
    # wrap_tool_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != self._tool_name:
            return handler(request)
        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != self._tool_name:
            return await handler(request)
        return self._handle_clarification(request)
