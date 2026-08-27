"""Unit tests for :mod:`agent_sdk.runtime.store`.

Covers the :func:`make_store` async context manager across
all backends.  Only the ``memory`` branch is exercised
end-to-end; the ``sqlite`` and ``postgres`` branches are
covered by import-error tests so we do not require the
optional extras to be installed.
"""

from __future__ import annotations

import re

import pytest
from agent_sdk.runtime.checkpointer import CheckpointerConfig
from agent_sdk.runtime.store import make_store
from agent_sdk.runtime.store.async_factory import (
    POSTGRES_STORE_INSTALL,
    SQLITE_STORE_INSTALL,
)

# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    async def test_default_yields_memory_store(self) -> None:
        async with make_store() as store:
            assert store.__class__.__name__ == "InMemoryStore"

    async def test_with_memory_config(self) -> None:
        cfg = CheckpointerConfig(type="memory")
        async with make_store(cfg) as store:
            assert store.__class__.__name__ == "InMemoryStore"

    async def test_with_sqlite_config_raises_helpfully(self) -> None:
        cfg = CheckpointerConfig(type="sqlite", connection_string=":memory:")
        with pytest.raises(ImportError, match=SQLITE_STORE_INSTALL):
            async with make_store(cfg) as store:
                _ = store  # pragma: no cover

    async def test_with_postgres_config_missing_conn_raises(self) -> None:
        cfg = CheckpointerConfig(type="postgres")
        with pytest.raises(ValueError, match="connection_string is required"):
            async with make_store(cfg) as store:
                _ = store  # pragma: no cover

    async def test_with_postgres_config_raises_helpfully(self) -> None:
        cfg = CheckpointerConfig(
            type="postgres",
            connection_string="postgresql://user:pass@localhost:5432/db",
        )
        with pytest.raises(ImportError, match=re.escape(POSTGRES_STORE_INSTALL)):
            async with make_store(cfg) as store:
                _ = store  # pragma: no cover

    async def test_unknown_type_raises(self) -> None:
        cfg = CheckpointerConfig.model_construct(type="redis", connection_string=None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown store backend type"):
            async with make_store(cfg) as store:
                _ = store  # pragma: no cover

    async def test_store_releases_on_exit(self) -> None:
        # The store should be functional inside the context
        # manager and the async-context-manager protocol
        # should exit cleanly.
        async with make_store() as store:
            assert store is not None
        # After exit, the context manager's __aexit__ has run;
        # nothing further to assert without a real backend.


# ---------------------------------------------------------------------------
# InMemoryStore end-to-end smoke
# ---------------------------------------------------------------------------


class TestInMemoryStoreEndToEnd:
    async def test_basic_put_and_get(self) -> None:
        from langgraph.store.memory import InMemoryStore

        async with make_store() as store:
            assert isinstance(store, InMemoryStore)
            await store.aput(("users",), "u-1", {"name": "alice"})
            item = await store.aget(("users",), "u-1")
            assert item is not None
            assert item.value == {"name": "alice"}
