"""TokenUsageMiddleware — log LLM token usage after each model call.

The middleware is a thin post-processor: after every model
response, it inspects the last :class:`AIMessage` for a
``usage_metadata`` field and logs the ``input_tokens`` /
``output_tokens`` / ``total_tokens`` triplet. The middleware
is purely observational — it never mutates state — so the
agent loop is unaffected.

**Brand-neutral**: this middleware is pure infrastructure. It
is part of the SDK's always-on chain.

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


class TokenUsageMiddleware(AgentMiddleware):
    """Log ``usage_metadata`` from the most recent :class:`AIMessage`.

    Runs inside the composed ``model`` graph node via
    :meth:`wrap_model_call` — never mutates state.
    """

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = handler(request)
        self._log_usage(response)
        return response

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = await handler(request)
        self._log_usage(response)
        return response

    def _log_usage(self, response: ModelResponse) -> None:
        """Inspect the model response and log its ``usage_metadata`` (if any).

        Includes cache metrics (``cache_read`` / ``cache_creation``) from
        ``input_token_details`` so operators can monitor prompt-cache hit
        rates without grepping state logs.
        """
        result = getattr(response, "result", None)
        if not result:
            return
        for msg in reversed(result):
            if isinstance(msg, AIMessage):
                usage = getattr(msg, "usage_metadata", None)
                if usage:
                    input_tokens = usage.get("input_tokens", "?")
                    output_tokens = usage.get("output_tokens", "?")
                    total_tokens = usage.get("total_tokens", "?")
                    input_details = usage.get("input_token_details", {}) or {}
                    cache_read = input_details.get("cache_read", 0) or 0
                    cache_creation = input_details.get("cache_creation", 0) or 0
                    cache_hit_pct = (
                        f"{cache_read / input_tokens * 100:.0f}%"
                        if isinstance(input_tokens, (int, float)) and input_tokens > 0
                        else "n/a"
                    )
                    logger.info(
                        "LLM token usage: input=%s output=%s total=%s "
                        "cache_read=%s cache_creation=%s cache_hit=%s",
                        input_tokens,
                        output_tokens,
                        total_tokens,
                        cache_read,
                        cache_creation,
                        cache_hit_pct,
                    )
                return