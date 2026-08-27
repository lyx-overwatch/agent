"""Sync checkpointer factory (singleton + context manager).

This module is a re-implementation (per ADR-010) of
``deerflow.runtime.checkpointer.provider``.  It exposes:

* :func:`get_checkpointer` — process-wide sync singleton,
  recreated lazily on first call.
* :func:`reset_checkpointer` — close any open backend
  connection and clear the cached instance.  Intended for
  tests and configuration changes.
* :func:`checkpointer_context` — one-shot sync context
  manager that does not cache; each ``with`` block opens and
  closes its own connection.

The sync path is intended for CLI tools, scripts, and tests
where the request/response model of the async path is not
needed.  Long-running servers should use the async factory
instead.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Checkpointer

from agent_sdk.runtime.checkpointer.config import CheckpointerConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

#: Error message for missing SQLite extras.
SQLITE_INSTALL: str = (
    "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. "
    "Install it with: uv add langgraph-checkpoint-sqlite"
)

#: Error message for missing Postgres extras.
POSTGRES_INSTALL: str = (
    "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. "
    "Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
)

#: Error message for missing Postgres connection string.
POSTGRES_CONN_REQUIRED: str = "checkpointer.connection_string is required for the postgres backend"


# ---------------------------------------------------------------------------
# Internal sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """Construct a sync checkpointer from *config* and tear it down on exit."""
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        _ensure_sqlite_parent_dir(conn_str)
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            yield saver
        return

    if config.type == "postgres":
        # Validate the connection string before the (potentially
        # failing) provider import so the user gets a clear
        # "missing connection string" error first when the
        # optional extras are not installed.
        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Connection-string helpers
# ---------------------------------------------------------------------------


def _resolve_sqlite_conn_str(raw: str) -> str:
    """Normalise a SQLite connection string.

    Maps the ``":memory:"`` pseudo-URL to langgraph's expected
    form and otherwise passes the value through unchanged.
    """
    if raw == ":memory:":
        return ":memory:"
    return raw


def _ensure_sqlite_parent_dir(conn_str: str) -> None:
    """Create the parent directory of a SQLite file if it does not yet exist.

    No-op for the ``":memory:"`` backend.
    """
    if conn_str == ":memory:":
        return
    from pathlib import Path

    parent = Path(conn_str).expanduser().parent
    parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------


_checkpointer: Checkpointer | None = None
_checkpointer_ctx: contextlib.AbstractContextManager[Checkpointer] | None = None
_config: CheckpointerConfig | None = None


def configure(config: CheckpointerConfig) -> None:
    """Set the checkpointer configuration used by the sync singleton.

    Subsequent calls to :func:`get_checkpointer` will build a
    checkpointer from this configuration.  Pass ``None`` to
    fall back to the default in-memory saver.
    """
    global _config
    _config = config


def get_checkpointer() -> Checkpointer:
    """Return the global sync checkpointer singleton.

    The first call constructs the checkpointer from the
    :class:`CheckpointerConfig` registered via
    :func:`configure` (or, if none is registered, an
    :class:`InMemorySaver`).

    Returns:
        A :class:`Checkpointer` instance, cached for the
        lifetime of the process.
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    if _config is None:
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (no config registered)")
        _checkpointer = InMemorySaver()
        return _checkpointer

    _checkpointer_ctx = _sync_checkpointer_cm(_config)
    _checkpointer = _checkpointer_ctx.__enter__()
    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, closing any open backend connection.

    Useful in tests or after a configuration change.  After
    this call, the next :func:`get_checkpointer` will build a
    fresh checkpointer.
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            _checkpointer_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during checkpointer cleanup", exc_info=True)
        _checkpointer_ctx = None
    _checkpointer = None


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context(config: CheckpointerConfig | None = None) -> Iterator[Checkpointer]:
    """Sync context manager that yields a checkpointer and tears it down on exit.

    Unlike :func:`get_checkpointer`, this does **not** cache
    the instance — each ``with`` block creates and destroys
    its own connection.  Use it in CLI scripts or tests
    where you want deterministic cleanup.

    Args:
        config: Optional configuration.  When ``None``, an
            :class:`InMemorySaver` is yielded.

    Yields:
        A :class:`Checkpointer` ready to be passed to
        ``graph.compile(checkpointer=...)`` or
        ``graph.invoke(input, config=...)``.
    """
    if config is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    with _sync_checkpointer_cm(config) as saver:
        yield saver


# Re-export BaseCheckpointSaver so callers can type-annotate
# the result without an extra langgraph import.
__all__ = [
    "BaseCheckpointSaver",
    "POSTGRES_CONN_REQUIRED",
    "POSTGRES_INSTALL",
    "SQLITE_INSTALL",
    "checkpointer_context",
    "configure",
    "get_checkpointer",
    "reset_checkpointer",
]
