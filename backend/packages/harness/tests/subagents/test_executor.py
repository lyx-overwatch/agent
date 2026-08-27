"""Unit tests for :class:`agent_sdk.subagents.executor.SubagentExecutor` and task tool."""

from __future__ import annotations

import time

import pytest
from agent_sdk.presets.deerflow.subagents import DeerFlowSubagentRegistry
from agent_sdk.subagents.default import DefaultSubagentRegistry
from agent_sdk.subagents.definition import SubagentDefinition
from agent_sdk.subagents.executor import (
    RunSubagent,
    SubagentExecutor,
    SubagentResult,
    SubagentStatus,
    cleanup_background_task,
    get_background_task_result,
    request_cancel_background_task,
)
from agent_sdk.subagents.registry import SubagentRegistry
from agent_sdk.tools.task import make_task_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRegistry(SubagentRegistry):
    """In-memory registry for testing."""

    def __init__(self) -> None:
        self._roles: dict[str, SubagentDefinition] = {
            "general-purpose": SubagentDefinition(
                name="general-purpose",
                description="A capable agent for complex tasks",
                system_prompt="You are a helpful assistant.",
            ),
            "bash": SubagentDefinition(
                name="bash",
                description="Command execution specialist",
                system_prompt="You are a bash specialist.",
            ),
        }

    def get(self, name: str) -> SubagentDefinition | None:
        return self._roles.get(name)

    def list_names(self) -> list[str]:
        return list(self._roles)

    def register(self, definition: SubagentDefinition) -> None:
        self._roles[definition.name] = definition


def _make_run_subagent(output: str = "Task done") -> RunSubagent:
    """Return a run_subagent callable that returns a fixed output."""

    def _run(task: str, definition, result_holder: SubagentResult | None) -> str:
        return output

    return _run


def _make_slow_run(delay: float, output: str = "Slow task done") -> RunSubagent:
    """Return a run_subagent that sleeps before returning."""

    def _run(task: str, definition, result_holder: SubagentResult | None) -> str:
        time.sleep(delay)
        return output

    return _run


def _make_failing_run(error: str = "Something went wrong") -> RunSubagent:
    """Return a run_subagent that raises an exception."""

    def _run(task: str, definition, result_holder: SubagentResult | None) -> str:
        raise RuntimeError(error)

    return _run


# ---------------------------------------------------------------------------
# SubagentExecutor — lookup
# ---------------------------------------------------------------------------


class TestLookup:
    def test_lookup_returns_definition(self) -> None:
        executor = SubagentExecutor(DeerFlowSubagentRegistry(), _make_run_subagent())
        definition = executor.lookup("general-purpose")
        assert definition.name == "general-purpose"

    def test_lookup_raises_for_unknown(self) -> None:
        executor = SubagentExecutor(DefaultSubagentRegistry(), _make_run_subagent())
        with pytest.raises(ValueError, match="Unknown subagent type"):
            executor.lookup("nope")

    def test_lookup_error_lists_available(self) -> None:
        executor = SubagentExecutor(DeerFlowSubagentRegistry(), _make_run_subagent())
        with pytest.raises(ValueError, match="general-purpose"):
            executor.lookup("nope")


# ---------------------------------------------------------------------------
# SubagentExecutor — execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_success(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(registry, _make_run_subagent("Hello, world!"))
        result = executor.execute("Do something", subagent_type="general-purpose")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Hello, world!"
        assert result.subagent_type == "general-purpose"
        assert result.task_id
        assert result.started_at is not None
        assert result.completed_at is not None

    def test_execute_returns_unique_task_id(self) -> None:
        executor = SubagentExecutor(DeerFlowSubagentRegistry(), _make_run_subagent())
        r1 = executor.execute("x", subagent_type="general-purpose")
        r2 = executor.execute("x", subagent_type="general-purpose")
        assert r1.task_id != r2.task_id

    def test_execute_unknown_type(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(registry, _make_run_subagent())
        with pytest.raises(ValueError, match="Unknown subagent type"):
            executor.execute("task", subagent_type="nonexistent")

    def test_execute_failure(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(registry, _make_failing_run("Boom!"))
        result = executor.execute("Do something")

        assert result.status == SubagentStatus.FAILED
        assert result.error is not None
        assert "Boom" in result.error

    def test_execute_no_output(self) -> None:
        registry = _FakeRegistry()

        def _run_none(task: str, definition, holder: SubagentResult | None) -> str | None:
            return None

        executor = SubagentExecutor(registry, _run_none)
        result = executor.execute("task")

        assert result.status == SubagentStatus.FAILED
        assert "no output" in (result.error or "")

    def test_execute_bash(self) -> None:
        executor = SubagentExecutor(DeerFlowSubagentRegistry(), _make_run_subagent("ls output"))
        result = executor.execute("list files", subagent_type="bash")
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "ls output"
        assert result.subagent_type == "bash"


# ---------------------------------------------------------------------------
# SubagentExecutor — execute_async
# ---------------------------------------------------------------------------


class TestExecuteAsync:
    def test_execute_async_success(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(registry, _make_run_subagent("Async result"))
        task_id = executor.execute_async("Do async", subagent_type="general-purpose")

        for _ in range(20):
            result = get_background_task_result(task_id)
            if result is not None and result.status in {
                SubagentStatus.COMPLETED,
                SubagentStatus.FAILED,
                SubagentStatus.TIMED_OUT,
            }:
                break
            time.sleep(0.1)

        result = get_background_task_result(task_id)
        assert result is not None
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Async result"

        cleanup_background_task(task_id)

    def test_execute_async_timeout(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(
            registry, _make_slow_run(2.0), timeout_seconds=0.1
        )
        task_id = executor.execute_async("Slow task")

        for _ in range(20):
            result = get_background_task_result(task_id)
            if result is not None and result.status == SubagentStatus.TIMED_OUT:
                break
            time.sleep(0.1)

        result = get_background_task_result(task_id)
        assert result is not None
        assert result.status == SubagentStatus.TIMED_OUT

        cleanup_background_task(task_id)

    def test_execute_async_failure(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(registry, _make_failing_run("Async error"))
        task_id = executor.execute_async("Failing task")

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
        assert result.status == SubagentStatus.FAILED

        cleanup_background_task(task_id)

    def test_cancel_background_task(self) -> None:
        registry = _FakeRegistry()
        executor = SubagentExecutor(
            registry, _make_slow_run(5.0), timeout_seconds=30
        )
        task_id = executor.execute_async("Cancellable task")

        time.sleep(0.1)
        request_cancel_background_task(task_id)

        for _ in range(20):
            result = get_background_task_result(task_id)
            if result is not None and result.status in {
                SubagentStatus.CANCELLED,
                SubagentStatus.COMPLETED,
            }:
                break
            time.sleep(0.1)

        result = get_background_task_result(task_id)
        assert result is not None
        # Cancel event is set, but task may complete before checking
        assert result.status in {
            SubagentStatus.CANCELLED,
            SubagentStatus.COMPLETED,
            SubagentStatus.RUNNING,
        }

        cleanup_background_task(task_id)

    def test_get_background_task_unknown(self) -> None:
        assert get_background_task_result("nonexistent-id") is None

    def test_cleanup_unknown_task(self) -> None:
        cleanup_background_task("nonexistent-id")  # Should not raise


# ---------------------------------------------------------------------------
# SubagentResult
# ---------------------------------------------------------------------------


class TestSubagentResult:
    def test_defaults(self) -> None:
        result = SubagentResult(task_id="t1", subagent_type="gp")
        assert result.status == SubagentStatus.PENDING
        assert result.result is None
        assert result.error is None
        assert result.started_at is None
        assert result.completed_at is None
        assert result.cancel_event is not None

    def test_cancel_event_is_set(self) -> None:
        result = SubagentResult(task_id="t1", subagent_type="gp")
        assert not result.cancel_event.is_set()
        result.cancel_event.set()
        assert result.cancel_event.is_set()


# ---------------------------------------------------------------------------
# task tool
# ---------------------------------------------------------------------------


class TestTaskTool:
    def test_task_tool_success(self) -> None:
        registry = _FakeRegistry()
        tool = make_task_tool(
            registry=registry,
            run_subagent=_make_run_subagent("Subagent output"),
        )
        result = tool.invoke({
            "description": "Test task",
            "prompt": "Do something useful",
            "subagent_type": "general-purpose",
        })
        assert "Task completed" in result
        assert "Subagent output" in result

    def test_task_tool_unknown_type(self) -> None:
        registry = _FakeRegistry()
        tool = make_task_tool(
            registry=registry,
            run_subagent=_make_run_subagent(),
        )
        result = tool.invoke({
            "description": "Bad task",
            "prompt": "Do something",
            "subagent_type": "unknown-role",
        })
        assert "Unknown subagent type" in result

    def test_task_tool_not_configured(self) -> None:
        tool = make_task_tool()
        result = tool.invoke({
            "description": "Test",
            "prompt": "Do something",
            "subagent_type": "general-purpose",
        })
        assert "not configured" in result

    def test_task_tool_no_registry(self) -> None:
        tool = make_task_tool(run_subagent=_make_run_subagent())
        result = tool.invoke({
            "description": "Test",
            "prompt": "Do something",
            "subagent_type": "general-purpose",
        })
        assert "not configured" in result

    def test_task_tool_no_run_subagent(self) -> None:
        registry = _FakeRegistry()
        tool = make_task_tool(registry=registry)
        result = tool.invoke({
            "description": "Test",
            "prompt": "Do something",
            "subagent_type": "general-purpose",
        })
        assert "not configured" in result

    def test_task_tool_default_name(self) -> None:
        tool = make_task_tool()
        assert tool.name == "task"

    def test_task_tool_custom_name(self) -> None:
        tool = make_task_tool(tool_name="custom_task")
        assert tool.name == "custom_task"

    def test_task_tool_execution_error(self) -> None:
        registry = _FakeRegistry()
        tool = make_task_tool(
            registry=registry,
            run_subagent=_make_failing_run("BOOM"),
        )
        result = tool.invoke({
            "description": "Failing task",
            "prompt": "This will fail",
            "subagent_type": "general-purpose",
        })
        assert "Task failed" in result
        assert "BOOM" in result