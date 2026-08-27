"""Integration tests for multi-thread isolation, Memory round-trip, and Subagent invocation.

These tests exercise cross-component flows that span multiple
SDK modules.
"""

from __future__ import annotations

import time

from agent_sdk.memory.middleware import MemoryMiddleware, MemoryMiddlewareState
from agent_sdk.memory.schema import MemorySchema
from agent_sdk.memory.storage import MemoryStorage
from agent_sdk.subagents.definition import SubagentDefinition
from agent_sdk.subagents.executor import (
    RunSubagent,
    SubagentExecutor,
    SubagentResult,
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
)
from agent_sdk.subagents.registry import SubagentRegistry
from agent_sdk.tools.task import make_task_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSchema(MemorySchema):
    """Minimal MemorySchema for integration testing."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {
            "userProfile": {},
            "conversationHistory": [],
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
        pass


class _FakeStorage(MemoryStorage[_FakeSchema]):
    """In-memory storage for integration testing."""

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


class _FakeRegistry(SubagentRegistry):
    def __init__(self) -> None:
        self._roles = {
            "general-purpose": SubagentDefinition(
                name="general-purpose",
                description="Test agent",
                system_prompt="You are helpful.",
            ),
        }

    def get(self, name: str) -> SubagentDefinition | None:
        return self._roles.get(name)

    def list_names(self) -> list[str]:
        return list(self._roles)

    def register(self, definition: SubagentDefinition) -> None:
        self._roles[definition.name] = definition


def _make_run_subagent(output: str = "Done") -> RunSubagent:
    def _run(task: str, definition, result_holder: SubagentResult | None) -> str:
        return output

    return _run


# ---------------------------------------------------------------------------
# Multi-thread isolation
# ---------------------------------------------------------------------------


class TestMultiThreadIsolation:
    """Verify that different thread_ids have isolated paths/storage."""

    def test_thread_isolation_in_memory_storage(self) -> None:
        """Different thread_ids get independent MemoryStorage instances."""
        storage_a = _FakeStorage()
        storage_b = _FakeStorage()

        # Populate thread A
        schema_a = _FakeSchema({"userProfile": {"name": "Alice"}, "conversationHistory": []})
        storage_a.save(schema_a)

        # Populate thread B
        schema_b = _FakeSchema({"userProfile": {"name": "Bob"}, "conversationHistory": []})
        storage_b.save(schema_b)

        # Verify isolation
        assert storage_a.load().get_user_profile() == {"name": "Alice"}
        assert storage_b.load().get_user_profile() == {"name": "Bob"}
        assert storage_a.load().get_user_profile() != storage_b.load().get_user_profile()

    def test_thread_isolation_middleware(self) -> None:
        """Different MemoryMiddleware instances with separate storage are isolated."""
        storage_a = _FakeStorage()
        storage_b = _FakeStorage()

        mw_a = MemoryMiddleware(_FakeSchema, storage_a)
        mw_b = MemoryMiddleware(_FakeSchema, storage_b)

        # Pre-populate with different data
        storage_a.save(_FakeSchema({"userProfile": {"name": "ThreadA"}, "conversationHistory": []}))
        storage_b.save(_FakeSchema({"userProfile": {"name": "ThreadB"}, "conversationHistory": []}))

        state_a: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        state_b: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]

        result_a = mw_a.before_agent(state_a, None)  # type: ignore[arg-type]
        result_b = mw_b.before_agent(state_b, None)  # type: ignore[arg-type]

        assert result_a["memory"]["user_profile"] == {"name": "ThreadA"}
        assert result_b["memory"]["user_profile"] == {"name": "ThreadB"}


# ---------------------------------------------------------------------------
# Memory round-trip
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    """Verify Memory write → persist → read end-to-end."""

    def test_memory_round_trip_before_after(self) -> None:
        """Memory loaded in before_agent, modified, and persisted in after_agent."""
        storage = _FakeStorage()
        mw = MemoryMiddleware(_FakeSchema, storage)

        # Initial state: empty memory
        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        before = mw.before_agent(state, None)  # type: ignore[arg-type]
        assert before["memory"]["user_profile"] == {}

        # Simulate agent modifying memory
        state["memory"] = {
            "user_profile": {"name": "Charlie", "role": "tester"},
            "conversation_history": [{"period": "2026-07", "summary": "Integration test"}],
        }

        # Persist
        mw.after_agent(state, None)  # type: ignore[arg-type]

        # Verify persistence
        saved = storage.load()
        assert saved.get_user_profile() == {"name": "Charlie", "role": "tester"}
        assert saved.get_conversation_history() == [{"period": "2026-07", "summary": "Integration test"}]

    def test_memory_persistence_across_loads(self) -> None:
        """Memory persists across multiple load cycles."""
        storage = _FakeStorage()
        mw = MemoryMiddleware(_FakeSchema, storage)

        # First round: write data
        state: MemoryMiddlewareState = {"messages": []}  # type: ignore[assignment]
        state["memory"] = {"user_profile": {"name": "First"}, "conversation_history": []}
        mw.after_agent(state, None)  # type: ignore[arg-type]

        # Second round: reload and verify
        before = mw.before_agent(state, None)  # type: ignore[arg-type]
        assert before["memory"]["user_profile"] == {"name": "First"}

        # Modify and persist again
        state["memory"] = {"user_profile": {"name": "Second"}, "conversation_history": []}
        mw.after_agent(state, None)  # type: ignore[arg-type]

        # Third round: verify updated data
        before = mw.before_agent(state, None)  # type: ignore[arg-type]
        assert before["memory"]["user_profile"] == {"name": "Second"}


# ---------------------------------------------------------------------------
# Subagent invocation
# ---------------------------------------------------------------------------


class TestSubagentIntegration:
    """Verify task tool → registry → executor end-to-end."""

    def test_subagent_invocation_flow(self) -> None:
        """Full flow: task tool validates subagent_type, executes, returns result."""
        registry = _FakeRegistry()
        tool = make_task_tool(
            registry=registry,
            run_subagent=_make_run_subagent("Subagent task output"),
        )

        result = tool.invoke({
            "description": "Integration test",
            "prompt": "Do something useful",
            "subagent_type": "general-purpose",
        })

        assert "Task completed" in result
        assert "Subagent task output" in result

    def test_subagent_unknown_type_error(self) -> None:
        """Task tool returns clear error for unknown subagent type."""
        registry = _FakeRegistry()
        tool = make_task_tool(
            registry=registry,
            run_subagent=_make_run_subagent(),
        )

        result = tool.invoke({
            "description": "Bad type",
            "prompt": "Do something",
            "subagent_type": "unknown-type",
        })

        assert "Unknown subagent type" in result
        assert "general-purpose" in result  # lists available types

    def test_subagent_executor_async_flow(self) -> None:
        """Subagent execution via execute_async + polling."""
        registry = _FakeRegistry()
        executor = SubagentExecutor(
            registry,
            _make_run_subagent("Async integration result"),
        )

        task_id = executor.execute_async("Integration task", subagent_type="general-purpose")

        # Poll until complete
        for _ in range(20):
            result = get_background_task_result(task_id)
            if result is not None and result.status in {
                SubagentStatus.COMPLETED,
                SubagentStatus.FAILED,
            }:
                break
            time.sleep(0.1)

        result = get_background_task_result(task_id)
        assert result is not None
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Async integration result"

        cleanup_background_task(task_id)

    def test_subagent_registry_custom_role(self) -> None:
        """Custom roles can be registered and used."""
        registry = _FakeRegistry()
        registry.register(SubagentDefinition(
            name="custom-role",
            description="A custom test role",
            system_prompt="You are a custom agent.",
        ))

        executor = SubagentExecutor(registry, _make_run_subagent("Custom output"))
        result = executor.execute("Custom task", subagent_type="custom-role")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Custom output"
        assert result.subagent_type == "custom-role"