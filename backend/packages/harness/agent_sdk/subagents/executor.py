"""SubagentExecutor — dispatches subtasks to a registered subagent.

This is a re-implementation (per ADR-010) of
``backend.subagents.executor.SubagentExecutor``.

The executor runs subagent tasks in a background thread pool with
timeout enforcement and cooperative cancellation.  The actual agent
execution is delegated to a *run* callable injected at construction
time, keeping the executor independent of any particular agent
framework.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from agent_sdk.subagents.registry import SubagentRegistry

logger = logging.getLogger(__name__)


class SubagentStatus(str, Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Unique identifier for this execution.
        subagent_type: The role name that was dispatched.
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed / timed out / cancelled).
        started_at: When execution started.
        completed_at: When execution completed.
    """

    task_id: str
    subagent_type: str
    status: SubagentStatus = SubagentStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


# ---------------------------------------------------------------------------
# Global background task bookkeeping
# ---------------------------------------------------------------------------

_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# Thread pool for background task scheduling
_scheduler_pool = ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="subagent-scheduler-"
)

# Thread pool for actual subagent execution
_execution_pool = ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="subagent-exec-"
)


def _get_background_task(task_id: str) -> SubagentResult | None:
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def _cleanup_background_task(task_id: str) -> None:
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is None:
            return
        is_terminal = result.status in {
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.CANCELLED,
            SubagentStatus.TIMED_OUT,
        }
        if is_terminal or result.completed_at is not None:
            del _background_tasks[task_id]


def request_cancel_background_task(task_id: str) -> None:
    """Signal a running background task to stop cooperatively."""
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is not None:
            result.cancel_event.set()


# ---------------------------------------------------------------------------
# Run callable type
# ---------------------------------------------------------------------------

RunSubagent = Callable[
    [str, "SubagentDefinition", SubagentResult | None],
    str | None,
]
"""Signature for a subagent execution function.

Args:
    task: The task description.
    definition: The subagent role definition (system prompt, tool
        allow/deny lists, model, timeouts, etc.).
    result_holder: Optional result object to update during execution.

Returns:
    The subagent's final text output, or ``None`` on failure.
"""


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class SubagentExecutor:
    """Dispatches subtasks to a :class:`SubagentRegistry`-backed role.

    Args:
        registry: Where to look up roles.
        run_subagent: Callable that executes a subagent task and
            returns the final text.  Called with
            ``(task, definition, result_holder)``.
        timeout_seconds: Maximum execution time per subagent
            (default: 900 = 15 minutes).
    """

    def __init__(
        self,
        registry: SubagentRegistry,
        run_subagent: RunSubagent,
        *,
        timeout_seconds: float = 900,
    ) -> None:
        self._registry = registry
        self._run = run_subagent
        self._timeout = timeout_seconds

    def lookup(self, subagent_type: str):
        """Return the role definition, raising ``ValueError`` if missing."""
        definition = self._registry.get(subagent_type)
        if definition is None:
            available = ", ".join(self._registry.list_names())
            raise ValueError(
                f"Unknown subagent type {subagent_type!r}. "
                f"Available: {available}"
            )
        return definition

    def execute(self, task: str, subagent_type: str = "general-purpose") -> SubagentResult:
        """Execute a task synchronously.

        Args:
            task: The task description.
            subagent_type: The role name (looked up in the registry).

        Returns:
            :class:`SubagentResult` with the execution result.
        """
        definition = self.lookup(subagent_type)
        task_id = str(uuid.uuid4())[:8]
        result = SubagentResult(
            task_id=task_id,
            subagent_type=definition.name,
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )

        try:
            output = self._run(task, definition, result)
            if output is None:
                result.status = SubagentStatus.FAILED
                result.error = result.error or "Subagent returned no output"
            else:
                result.status = SubagentStatus.COMPLETED
                result.result = output
        except Exception as exc:
            logger.exception("Subagent %s execution failed", definition.name)
            result.status = SubagentStatus.FAILED
            result.error = str(exc)
        finally:
            result.completed_at = datetime.now()

        return result

    def execute_async(self, task: str, subagent_type: str = "general-purpose", task_id: str | None = None) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description.
            subagent_type: The role name.
            task_id: Optional task ID.  Generated if not provided.

        Returns:
            Task ID that can be used with :func:`get_background_task_result`
            to poll for completion.
        """
        definition = self.lookup(subagent_type)
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        result = SubagentResult(
            task_id=task_id,
            subagent_type=definition.name,
            status=SubagentStatus.PENDING,
        )

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        def _run_in_background() -> None:
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now()
                holder = _background_tasks[task_id]

            try:
                future: Future = _execution_pool.submit(
                    self.execute, task, subagent_type
                )
                try:
                    exec_result = future.result(timeout=self._timeout)
                    with _background_tasks_lock:
                        _background_tasks[task_id].status = exec_result.status
                        _background_tasks[task_id].result = exec_result.result
                        _background_tasks[task_id].error = exec_result.error
                        _background_tasks[task_id].completed_at = datetime.now()
                except FuturesTimeoutError:
                    logger.error(
                        "Subagent %s timed out after %.0fs",
                        definition.name,
                        self._timeout,
                    )
                    with _background_tasks_lock:
                        if _background_tasks[task_id].status == SubagentStatus.RUNNING:
                            _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                            _background_tasks[task_id].error = (
                                f"Execution timed out after {self._timeout:.0f} seconds"
                            )
                            _background_tasks[task_id].completed_at = datetime.now()
                    holder.cancel_event.set()
                    future.cancel()
            except Exception as exc:
                logger.exception(
                    "Subagent %s background execution failed", definition.name
                )
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.FAILED
                    _background_tasks[task_id].error = str(exc)
                    _background_tasks[task_id].completed_at = datetime.now()

        _scheduler_pool.submit(_run_in_background)
        return task_id


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        task_id: The task ID returned by :meth:`SubagentExecutor.execute_async`.

    Returns:
        :class:`SubagentResult` if found, ``None`` otherwise.
    """
    return _get_background_task(task_id)


def cleanup_background_task(task_id: str) -> None:
    """Remove a completed background task from the registry."""
    _cleanup_background_task(task_id)