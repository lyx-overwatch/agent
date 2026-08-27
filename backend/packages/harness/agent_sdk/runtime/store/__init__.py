"""LangGraph store factory.

This package is a re-implementation (per ADR-010) of
``deerflow.runtime.store``.  It provides
:func:`make_store` — an async context manager that yields a
configured :class:`langgraph.store.base.BaseStore`.

The store and the checkpointer are intentionally
**independent** here.  The in-tree reference couples them so
that they always use the same backend; in the SDK each
function takes its own configuration.  A product that wants
to mirror the in-tree behaviour can call both factories with
the same :class:`CheckpointerConfig` instance.
"""

from agent_sdk.runtime.store.async_factory import make_store

__all__ = ["make_store"]
