"""Tracing factory — build callback handlers for LangSmith / Langfuse.

This module is a re-implementation (per ADR-010) of
``deerflow.tracing.factory``.  It exposes
:func:`build_tracing_callbacks` — a single function that
returns the list of callback handlers to attach to a chat
model (or to a compiled graph) based on a caller-supplied
:class:`TracingConfig`.

Both providers are imported lazily so the base install only
needs :mod:`langchain-core`.  When the optional package
is not installed, the factory logs a WARNING and skips that
provider — it never raises.  A caller that wants a hard
failure on missing deps can pass ``raise_on_missing=True``.
"""

from agent_sdk.tracing.factory import (
    LangfuseConfig,
    LangSmithConfig,
    TracingConfig,
    build_tracing_callbacks,
)

__all__ = [
    "LangSmithConfig",
    "LangfuseConfig",
    "TracingConfig",
    "build_tracing_callbacks",
]
