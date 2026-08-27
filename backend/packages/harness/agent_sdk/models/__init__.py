"""Model factory for SDK chat-model construction.

This package is a re-implementation (per ADR-010) of
``deerflow.models.factory``.  It exposes
:func:`create_chat_model` — a single entry point that builds
a :class:`langchain.chat_models.BaseChatModel` from a class
path and a kwargs dict, with optional tracing callback
attachment and a few useful defaults (e.g. auto-enabling
``stream_usage`` on OpenAI-compatible models).

The factory is **brand-neutral**: it knows nothing about
DeerFlow's specific model catalogue.  Products build their
own catalogue of :class:`ModelConfig` records and pass them
to this factory.  The DeerFlow preset provides its own
``DeerFlowModelConfig`` data class and a ``create_chat_model``
wrapper that knows the in-house defaults — see
:mod:`agent_sdk.presets.deerflow.models`.
"""

from agent_sdk.models.factory import ModelConfig, create_chat_model

__all__ = ["ModelConfig", "create_chat_model"]
