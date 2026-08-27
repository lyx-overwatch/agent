"""Unit tests for :mod:`agent_sdk.runtime.checkpointer`.

Covers the :class:`CheckpointerConfig` data class, the
sync singleton (:func:`get_checkpointer` / :func:`reset_checkpointer`),
the sync context manager (:func:`checkpointer_context`),
and the async context manager (:func:`make_checkpointer`).

The tests only cover the ``memory`` backend (always
available); the ``sqlite`` and ``postgres`` branches are
covered by import-error tests so we do not require the
optional extras to be installed.
"""

from __future__ import annotations

import re

import pytest
from agent_sdk.runtime.checkpointer import (
    CheckpointerConfig,
    checkpointer_context,
    get_checkpointer,
    make_checkpointer,
    reset_checkpointer,
)
from agent_sdk.runtime.checkpointer.factory import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
    SQLITE_INSTALL,
)

# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the sync singleton around each test."""
    reset_checkpointer()
    yield
    reset_checkpointer()


# ---------------------------------------------------------------------------
# CheckpointerConfig
# ---------------------------------------------------------------------------


class TestCheckpointerConfig:
    def test_defaults_to_memory(self) -> None:
        cfg = CheckpointerConfig()
        assert cfg.type == "memory"
        assert cfg.connection_string is None

    def test_explicit_memory(self) -> None:
        cfg = CheckpointerConfig(type="memory")
        assert cfg.type == "memory"

    def test_sqlite_requires_connection_string(self) -> None:
        # The data class does not validate at construction time;
        # the factory validates on use. We just confirm the
        # round-trip.
        cfg = CheckpointerConfig(type="sqlite", connection_string="store.db")
        assert cfg.type == "sqlite"
        assert cfg.connection_string == "store.db"

    def test_postgres_requires_connection_string(self) -> None:
        cfg = CheckpointerConfig(
            type="postgres",
            connection_string="postgresql://user:pass@localhost:5432/db",
        )
        assert cfg.type == "postgres"
        assert cfg.connection_string.startswith("postgresql://")

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValueError):
            CheckpointerConfig(type="redis")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sync singleton
# ---------------------------------------------------------------------------


class TestSyncSingleton:
    def test_get_checkpointer_returns_memory_saver_by_default(self) -> None:
        cp = get_checkpointer()
        # The exact class is an InMemorySaver (langgraph internal).
        assert cp.__class__.__name__ == "InMemorySaver"

    def test_singleton_caches(self) -> None:
        a = get_checkpointer()
        b = get_checkpointer()
        assert a is b

    def test_reset_clears_cache(self) -> None:
        a = get_checkpointer()
        reset_checkpointer()
        b = get_checkpointer()
        assert a is not b

    def test_singleton_with_sqlite_config_raises_helpfully(self) -> None:
        # Without the optional extra installed, we get a
        # well-formed ImportError pointing to the right
        # extras package.
        from agent_sdk.runtime.checkpointer.factory import configure

        configure(CheckpointerConfig(type="sqlite", connection_string=":memory:"))
        with pytest.raises(ImportError, match=SQLITE_INSTALL):
            get_checkpointer()

    def test_singleton_with_postgres_config_missing_conn_raises(self) -> None:
        from agent_sdk.runtime.checkpointer.factory import configure

        configure(CheckpointerConfig(type="postgres"))
        with pytest.raises(ValueError, match=POSTGRES_CONN_REQUIRED):
            get_checkpointer()

    def test_singleton_with_postgres_config_raises_helpfully(self) -> None:
        from agent_sdk.runtime.checkpointer.factory import configure

        configure(
            CheckpointerConfig(
                type="postgres",
                connection_string="postgresql://user:pass@localhost:5432/db",
            )
        )
        with pytest.raises(ImportError, match=re.escape(POSTGRES_INSTALL)):
            get_checkpointer()


# ---------------------------------------------------------------------------
# Sync context manager
# ---------------------------------------------------------------------------


class TestSyncContextManager:
    def test_default_yields_memory_saver(self) -> None:
        with checkpointer_context() as cp:
            assert cp.__class__.__name__ == "InMemorySaver"

    def test_with_memory_config(self) -> None:
        cfg = CheckpointerConfig(type="memory")
        with checkpointer_context(cfg) as cp:
            assert cp.__class__.__name__ == "InMemorySaver"

    def test_with_sqlite_config_raises_helpfully(self) -> None:
        cfg = CheckpointerConfig(type="sqlite", connection_string=":memory:")
        with pytest.raises(ImportError, match=SQLITE_INSTALL):
            with checkpointer_context(cfg) as cp:
                _ = cp  # pragma: no cover

    def test_with_postgres_config_missing_conn_raises(self) -> None:
        cfg = CheckpointerConfig(type="postgres")
        with pytest.raises(ValueError, match=POSTGRES_CONN_REQUIRED):
            with checkpointer_context(cfg) as cp:
                _ = cp  # pragma: no cover

    def test_unknown_type_raises(self) -> None:
        # Bypass pydantic validation to test the factory itself
        cfg = CheckpointerConfig.model_construct(type="redis", connection_string=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown checkpointer type"):
            with checkpointer_context(cfg) as cp:
                _ = cp  # pragma: no cover


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    async def test_default_yields_memory_saver(self) -> None:
        async with make_checkpointer() as cp:
            assert cp.__class__.__name__ == "InMemorySaver"

    async def test_with_memory_config(self) -> None:
        cfg = CheckpointerConfig(type="memory")
        async with make_checkpointer(cfg) as cp:
            assert cp.__class__.__name__ == "InMemorySaver"

    async def test_with_sqlite_config_raises_helpfully(self) -> None:
        cfg = CheckpointerConfig(type="sqlite", connection_string=":memory:")
        with pytest.raises(ImportError, match=SQLITE_INSTALL):
            async with make_checkpointer(cfg) as cp:
                _ = cp  # pragma: no cover

    async def test_with_postgres_config_missing_conn_raises(self) -> None:
        cfg = CheckpointerConfig(type="postgres")
        with pytest.raises(ValueError, match=POSTGRES_CONN_REQUIRED):
            async with make_checkpointer(cfg) as cp:
                _ = cp  # pragma: no cover

    async def test_unknown_type_raises(self) -> None:
        cfg = CheckpointerConfig.model_construct(type="redis", connection_string=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown checkpointer type"):
            async with make_checkpointer(cfg) as cp:
                _ = cp  # pragma: no cover
