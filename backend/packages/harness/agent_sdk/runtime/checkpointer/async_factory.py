"""Async checkpointer factory.

This module is a re-implementation (per ADR-010) of
``deerflow.runtime.checkpointer.async_provider``.  It exposes
:func:`make_checkpointer` — an async context manager for
long-running async servers (e.g. FastAPI lifespan, ASGI apps)
that need proper resource cleanup.

Supported backends: ``memory``, ``sqlite``, ``postgres``.
SQLite and postgres are imported lazily so the base install
only needs :mod:`langgraph`.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from agent_sdk.runtime.checkpointer.config import CheckpointerConfig
from agent_sdk.runtime.checkpointer.factory import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
    SQLITE_INSTALL,
    _ensure_sqlite_parent_dir,
    _resolve_sqlite_conn_str,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_checkpointer(config: CheckpointerConfig) -> AsyncIterator[Checkpointer]:
    """Construct an async checkpointer from *config* and tear it down on exit."""
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        import asyncio

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        await asyncio.to_thread(_ensure_sqlite_parent_dir, conn_str)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            yield saver
        return

    if config.type == "postgres":
        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        # Use AsyncConnectionPool instead of a single connection so
        # concurrent conversations get their own connections.
        # A single AsyncConnection triggers psycopg.OperationalError
        # ("another command is already in progress") when multiple
        # agent executions hit the checkpointer simultaneously.
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            config.connection_string,
            min_size=2,
            max_size=10,
            open=False,
            # 每次从池中取连接前执行一次空查询探活（等价 SELECT 1），
            # 把 Postgres 重启 / 网络闪断后残留的「死连接」在 checkout
            # 时丢弃重建，而不是等到 checkpoint 读写时才抛 OperationalError。
            check=AsyncConnectionPool.check_connection,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        await pool.open()
        try:
            saver = AsyncPostgresSaver(conn=pool)
            await saver.setup()
            yield saver
        finally:
            await pool.close()
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Public async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_checkpointer(config: CheckpointerConfig | None = None) -> AsyncIterator[Checkpointer]:
    """Async context manager that yields a checkpointer for the caller's lifetime.

    Resources are opened on enter and closed on exit.  No
    global state is touched.

    Example (FastAPI lifespan)::

        async with make_checkpointer(config) as checkpointer:
            app.state.checkpointer = checkpointer

    Args:
        config: Optional :class:`CheckpointerConfig`.  When
            ``None``, an :class:`InMemorySaver` is yielded.

    Yields:
        A :class:`Checkpointer` ready to be passed to
        ``graph.compile(checkpointer=...)`` or to
        ``graph.ainvoke(input, config=...)``.
    """
    if config is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    async with _async_checkpointer(config) as saver:
        yield saver
