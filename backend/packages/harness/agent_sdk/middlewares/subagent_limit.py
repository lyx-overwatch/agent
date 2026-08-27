"""SubagentLimitMiddleware — enforce a per-turn cap on ``task`` tool calls.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.subagent_limit_middleware``.

When the LLM generates more than ``max_concurrent`` parallel
``task`` tool calls in a single response, this middleware
keeps only the first ``max_concurrent`` and discards the rest.
This is more reliable than prompt-based limits because it
operates after the model has already produced the calls.

The cap is clamped to the in-tree reference range ``[2, 4]``,
which matches the limits the subagent executor enforces for
thread / process concurrency. Out-of-range values are silently
clamped (logged at WARNING the first time the middleware is
constructed) so a misconfigured preset does not crash the
agent at first call.

Uses :meth:`wrap_model_call` so it composes into the single
``model`` graph node instead of creating a separate
``after_model`` node — saving 1 recursion_limit step per
iteration.
"""

from __future__ import annotations

import logging
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

#: Default per-turn cap. Matches the in-tree
#: ``MAX_CONCURRENT_SUBAGENTS = 3`` constant.
DEFAULT_MAX_CONCURRENT: int = 3

#: Lower / upper bound the runtime enforces on user-supplied caps.
MIN_SUBAGENT_LIMIT: int = 2
MAX_SUBAGENT_LIMIT: int = 4

#: The tool name this middleware watches for. Must match the
#: ``task`` tool registered by :class:`SubagentRegistry`.
TASK_TOOL_NAME: str = "task"


def _clamp_subagent_limit(value: int) -> int:
    """Clamp *value* to the valid ``[MIN_SUBAGENT_LIMIT, MAX_SUBAGENT_LIMIT]`` range."""
    return max(MIN_SUBAGENT_LIMIT, min(MAX_SUBAGENT_LIMIT, value))


class SubagentLimitMiddleware(AgentMiddleware):
    """Truncate excess ``task`` tool calls from a single model response.

    Args:
        max_concurrent: Maximum number of concurrent subagent
            calls allowed. Defaults to
            :data:`DEFAULT_MAX_CONCURRENT` (3). Values outside
            ``[2, 4]`` are clamped.
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)

    @staticmethod
    def _truncate_task_calls_in_message(last_msg: AIMessage, max_concurrent: int) -> AIMessage | None:
        """Return a truncated copy of *last_msg* if it has too many ``task`` calls, or ``None``."""
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == TASK_TOOL_NAME]
        if len(task_indices) <= max_concurrent:
            return None

        indices_to_drop = set(task_indices[max_concurrent:])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]

        dropped_count = len(indices_to_drop)
        logger.warning(
            "Truncated %d excess task tool call(s) from model response (limit: %d)",
            dropped_count,
            max_concurrent,
        )

        return last_msg.model_copy(update={"tool_calls": truncated_tool_calls})

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = handler(request)
        return self._apply(response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = await handler(request)
        return self._apply(response)

    def _apply(self, response: ModelResponse) -> ModelResponse:
        result = getattr(response, "result", None)
        if not result:
            return response

        modified = False
        new_result = []
        for msg in result:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                truncated = self._truncate_task_calls_in_message(msg, self.max_concurrent)
                if truncated is not None:
                    new_result.append(truncated)
                    modified = True
                    continue
            new_result.append(msg)

        if modified:
            return ModelResponse(
                result=new_result,
                structured_response=response.structured_response,
            )
        return response