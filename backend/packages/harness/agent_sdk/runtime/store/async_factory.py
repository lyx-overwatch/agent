"""Async store factory.

This module is a re-implementation (per ADR-010) of
``deerflow.runtime.store.async_provider``.  It exposes
:func:`make_store` — an async context manager for long-running
async servers.

Supported backends: ``memory``, ``sqlite``, ``postgres``.
SQLite and postgres are imported lazily so the base install
only needs :mod:`langgraph`.

Why brand-neutral
-----------------
The in-tree reference couples the store to the same
:class:`CheckpointerConfig` that drives the checkpointer, so
that both share a single persistence backend.  In the SDK we
take the lighter position: :func:`make_store` takes its own
:class:`CheckpointerConfig` and the two factories are
independent.  Products that want the in-tree behaviour can
pass the same config to both.  This is documented as the
recommended pattern, not enforced.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.store.base import BaseStore

from agent_sdk.runtime.checkpointer.config import CheckpointerConfig
from agent_sdk.runtime.checkpointer.factory import (
    POSTGRES_CONN_REQUIRED,
    _ensure_sqlite_parent_dir,
    _resolve_sqlite_conn_str,
)

logger = logging.getLogger(__name__)

#: Error message for missing SQLite store extras.
SQLITE_STORE_INSTALL: str = (
    "langgraph-checkpoint-sqlite is required for the SQLite store. "
    "Install it with: uv add langgraph-checkpoint-sqlite"
)

#: Error message for missing Postgres store extras.
POSTGRES_STORE_INSTALL: str = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL store. "
    "Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
)


# ---------------------------------------------------------------------------
# Internal async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_store(config: CheckpointerConfig) -> AsyncIterator[BaseStore]:
    """Construct an async store from *config* and tear it down on exit.

    The *config* argument is a :class:`CheckpointerConfig`
    (re-used for the type tag, not for any checkpointer-
    specific field).
    """
    if config.type == "memory":
        from langgraph.store.memory import InMemoryStore

        logger.info("Store: using InMemoryStore (in-process, not persistent)")
        yield InMemoryStore()
        return

    if config.type == "sqlite":
        try:
            from langgraph.store.sqlite.aio import AsyncSqliteStore
        except ImportError as exc:
            raise ImportError(SQLITE_STORE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        _ensure_sqlite_parent_dir(conn_str)

        async with AsyncSqliteStore.from_conn_string(conn_str) as store:
            await store.setup()
            logger.info("Store: using AsyncSqliteStore (%s)", conn_str)
            yield store
        return

    if config.type == "postgres":
        # Validate the connection string before the (potentially
        # failing) provider import so the user gets a clear
        # "missing connection string" error first when the
        # optional extras are not installed.
        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(POSTGRES_STORE_INSTALL) from exc

        async with AsyncPostgresStore.from_conn_string(config.connection_string) as store:
            await store.setup()
            logger.info("Store: using AsyncPostgresStore")
            yield store
        return

    raise ValueError(f"Unknown store backend type: {config.type!r}")


# ---------------------------------------------------------------------------
# Public async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_store(config: CheckpointerConfig | None = None) -> AsyncIterator[BaseStore]:
    """Async context manager that yields a :class:`BaseStore`.

    Example (FastAPI lifespan)::

        async with make_store(config) as store:
            app.state.store = store

    Args:
        config: Optional :class:`CheckpointerConfig`.  When
            ``None``, an :class:`InMemoryStore` is yielded
            (with a WARNING — store data will be lost on
            process restart).

    Yields:
        A :class:`BaseStore` ready to be passed to
        ``graph.compile(store=...)``.
    """
    if config is None:
        from langgraph.store.memory import InMemoryStore

        logger.warning(
            "No checkpointer config provided — using InMemoryStore for the store. "
            "Store data will be lost on server restart. Configure a sqlite or postgres "
            "backend for persistence."
        )
        yield InMemoryStore()
        return

    async with _async_store(config) as store:
        yield store
