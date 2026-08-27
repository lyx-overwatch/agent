"""ModelCallCaptureMiddleware — record every LLM API call for forensics.

This middleware wraps ``awrap_model_call`` (and its sync counterpart)
to push a summary of the messages array to a per-request collector
(:func:`agent_sdk.state_logger.collect_model_call`).  The collector is
drained after the run by the caller (e.g. ``chat_service.py``) and
persisted alongside the state log so every model request is traceable.

The middleware is brand-neutral and always-on in the SDK chain.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

from agent_sdk.middlewares.state_logger import collect_model_call

logger = logging.getLogger(__name__)


class ModelCallCaptureMiddleware(AgentMiddleware):
    """Push a summary of each model call to the per-request collector."""

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        collect_model_call(request.messages)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        collect_model_call(request.messages)
        return await handler(request)
