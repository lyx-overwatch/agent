"""Tests for :class:`agent_sdk.memory.middleware.MemoryMiddleware`."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_sdk.memory.middleware import MemoryMiddleware, MemoryMiddlewareState
from agent_sdk.memory.schema import MemorySchema
from agent_sdk.memory.storage import MemoryStorage


class _FakeSchema(MemorySchema):
    """Minimal MemorySchema implementation for testing."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {
            "userProfile": {"name": "Test User", "role": "developer"},
            "conversationHistory": [{"period": "2026-07", "summary": "Testing"}],
        }

    def to_dict(self) -> dict:
        return dict(self._data)

    @classmethod
    def from_dict(cls, data: dict) -> _FakeSchema:
        return cls(data)

    def get_user_profile(self) -> dict[str, str]:
        return self._data.get("userProfile", {})

    def get_conversation_history(self) -> list[dict[str, str]]:
        return self._data.get("conversationHistory", [])

    @classmethod
    def empty(cls) -> _FakeSchema:
        return cls({"userProfile": {}, "conversationHistory": []})

    def touch(self) -> None:
        """Update timestamp (no-op for tests)."""
        pass


class _FakeStorage(MemoryStorage[_FakeSchema]):
    """In-memory storage for testing."""

    def __init__(self) -> None:
        self._data: _FakeSchema | None = None

    def load(self) -> _FakeSchema:
        if self._data is None:
            self._data = _FakeSchema.empty()
        return self._data

    def reload(self) -> _FakeSchema:
        return self.load()

    def save(self, schema: _FakeSchema) -> bool:
        self._data = schema
        return True


class TestMemoryMiddleware:
    """Tests for MemoryMiddleware before_agent and after_agent."""

    def _make_middleware(self) -> tuple[MemoryMiddleware[_FakeSchema], _FakeStorage]:
        storage = _FakeStorage()
        mw = MemoryMiddleware(_FakeSchema, storage)
        return mw, storage

    def _make_runtime(self) -> MagicMock:
        rt = MagicMock()
        rt.context = {}
        return rt

    # ------------------------------------------------------------------
    # before_agent
    # ------------------------------------------------------------------

    def test_before_agent_injects_user_profile(self) -> None:
        mw, storage = self._make_middleware()
        schema = _FakeSchema({"userProfile": {"name": "Alice"}, "conversationHistory": []})
        storage.save(schema)

        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        result = mw.before_agent(state, self._make_runtime())

        assert result is not None
        assert result["memory"]["user_profile"] == {"name": "Alice"}
        assert result["memory"]["conversation_history"] == []

    def test_before_agent_empty_storage(self) -> None:
        mw, _storage = self._make_middleware()
        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        result = mw.before_agent(state, self._make_runtime())

        assert result is not None
        assert result["memory"]["user_profile"] == {}
        assert result["memory"]["conversation_history"] == []

    # ------------------------------------------------------------------
    # after_agent
    # ------------------------------------------------------------------

    def test_after_agent_persists_updated_profile(self) -> None:
        mw, storage = self._make_middleware()
        state: MemoryMiddlewareState = {
            "messages": [],
            "memory": {
                "user_profile": {"name": "Bob", "role": "engineer"},
                "conversation_history": [],
            },
        }  # type: ignore[assignment]

        result = mw.after_agent(state, self._make_runtime())
        assert result is None  # no state changes

        # Verify storage was updated
        saved = storage.load()
        assert saved.get_user_profile() == {"name": "Bob", "role": "engineer"}

    def test_after_agent_persists_conversation_history(self) -> None:
        mw, storage = self._make_middleware()
        history = [
            {"period": "2026-07", "summary": "Discussed architecture"},
            {"period": "2026-06", "summary": "Initial setup"},
        ]
        state: MemoryMiddlewareState = {
            "messages": [],
            "memory": {
                "user_profile": {},
                "conversation_history": history,
            },
        }  # type: ignore[assignment]

        mw.after_agent(state, self._make_runtime())

        saved = storage.load()
        assert saved.get_conversation_history() == history

    def test_after_agent_no_memory_state(self) -> None:
        mw, storage = self._make_middleware()
        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]

        result = mw.after_agent(state, self._make_runtime())
        assert result is None

    def test_after_agent_empty_memory_values_skipped(self) -> None:
        mw, storage = self._make_middleware()
        # Pre-populate storage with known data
        storage.save(_FakeSchema({"userProfile": {"name": "Original"}, "conversationHistory": []}))

        state: MemoryMiddlewareState = {
            "messages": [],
            "memory": {
                "user_profile": {},  # empty — should be skipped
                "conversation_history": [],  # empty — should be skipped
            },
        }  # type: ignore[assignment]

        mw.after_agent(state, self._make_runtime())

        # Original data should be preserved (empty values are skipped)
        saved = storage.load()
        assert saved.get_user_profile() == {"name": "Original"}

    def test_round_trip_before_after(self) -> None:
        """End-to-end: before_agent loads, after_agent saves."""
        mw, storage = self._make_middleware()

        # Pre-populate
        storage.save(_FakeSchema({
            "userProfile": {"name": "Start"},
            "conversationHistory": [],
        }))

        # before_agent
        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        before = mw.before_agent(state, self._make_runtime())
        assert before["memory"]["user_profile"] == {"name": "Start"}

        # Simulate agent modifying memory
        state["memory"] = {
            "user_profile": {"name": "Updated"},
            "conversation_history": [{"period": "2026-07", "summary": "Done"}],
        }

        # after_agent
        mw.after_agent(state, self._make_runtime())

        # Verify persistence
        saved = storage.load()
        assert saved.get_user_profile() == {"name": "Updated"}
        assert saved.get_conversation_history() == [{"period": "2026-07", "summary": "Done"}]