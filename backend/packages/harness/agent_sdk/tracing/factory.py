"""Tracing factory.

This module is a re-implementation (per ADR-010) of
``deerflow.tracing.factory``.  It exposes
:func:`build_tracing_callbacks` plus three pydantic data
classes for declarative configuration.

Supported providers:

* ``"langsmith"`` — needs the ``LANGSMITH_*`` environment
  variables (or the explicit ``project`` field).  Backed by
  :class:`langchain_core.tracers.langchain.LangChainTracer`.
* ``"langfuse"`` — needs the ``LANGFUSE_*`` environment
  variables (or the explicit ``secret_key`` / ``public_key``
  / ``host`` fields).  Backed by
  :class:`langfuse.langchain.CallbackHandler`.

Both providers are imported lazily so the base install only
needs :mod:`langchain-core`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------


class LangSmithConfig(BaseModel):
    """LangSmith tracing configuration.

    Attributes:
        project: LangSmith project name.  When omitted, the
            ``LANGCHAIN_PROJECT`` / ``LANGSMITH_PROJECT``
            environment variable is used.
    """

    project: str | None = None


class LangfuseConfig(BaseModel):
    """Langfuse tracing configuration.

    Attributes:
        secret_key: Langfuse secret key.  When omitted, the
            ``LANGFUSE_SECRET_KEY`` environment variable is
            used.
        public_key: Langfuse public key.  When omitted, the
            ``LANGFUSE_PUBLIC_KEY`` environment variable is
            used.
        host: Langfuse host URL.  When omitted, the
            ``LANGFUSE_HOST`` environment variable is used
            (defaulting to the public Langfuse cloud).
    """

    secret_key: str | None = None
    public_key: str | None = None
    host: str | None = None


class TracingConfig(BaseModel):
    """Top-level tracing configuration.

    Attributes:
        providers: Names of the providers to enable.  Order
            is preserved in the returned callback list.
        langsmith: LangSmith configuration (only used when
            ``"langsmith"`` is in *providers*).
        langfuse: Langfuse configuration (only used when
            ``"langfuse"`` is in *providers*).
    """

    providers: list[Literal["langsmith", "langfuse"]] = Field(default_factory=list)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)


# ---------------------------------------------------------------------------
# Provider constructors (lazy imports)
# ---------------------------------------------------------------------------


def _create_langsmith_tracer(config: LangSmithConfig) -> Any:
    """Build a LangSmith :class:`LangChainTracer`."""
    from langchain_core.tracers.langchain import LangChainTracer

    return LangChainTracer(project_name=config.project)


def _create_langfuse_handler(config: LangfuseConfig) -> Any:
    """Build a Langfuse ``CallbackHandler``.

    langfuse>=4 initialises project-specific credentials
    through the client singleton; the LangChain callback
    then attaches to that configured client.
    """
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    Langfuse(
        secret_key=config.secret_key,
        public_key=config.public_key,
        host=config.host,
    )
    return LangfuseCallbackHandler(public_key=config.public_key)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_tracing_callbacks(
    config: TracingConfig | None = None,
    *,
    raise_on_missing: bool = False,
) -> list[Any]:
    """Build callback handlers for each enabled tracing provider.

    Args:
        config: Optional :class:`TracingConfig`.  When
            ``None``, no callbacks are returned.
        raise_on_missing: When ``True``, a failure to import
            a provider's optional dependency raises
            :class:`RuntimeError`.  When ``False`` (the
            default), the failure is logged at WARNING level
            and the provider is silently skipped.

    Returns:
        A list of callback handlers in the order the
        providers appear in *config.providers*.  Empty when
        no providers are configured.
    """
    if config is None or not config.providers:
        return []

    callbacks: list[Any] = []
    for provider in config.providers:
        if provider == "langsmith":
            try:
                callbacks.append(_create_langsmith_tracer(config.langsmith))
            except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
                msg = f"LangSmith tracing initialization failed: {exc}"
                if raise_on_missing:
                    raise RuntimeError(msg) from exc
                logger.warning(msg)
        elif provider == "langfuse":
            try:
                callbacks.append(_create_langfuse_handler(config.langfuse))
            except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
                msg = f"Langfuse tracing initialization failed: {exc}"
                if raise_on_missing:
                    raise RuntimeError(msg) from exc
                logger.warning(msg)
        else:
            logger.warning("Unknown tracing provider %r; skipping.", provider)
    return callbacks
