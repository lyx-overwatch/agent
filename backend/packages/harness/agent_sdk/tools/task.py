"""task tool factory.

Delegates a subtask to a subagent role registered in
:class:`agent_sdk.subagents.SubagentRegistry`.

This is a re-implementation (per ADR-010) of
``deerflow.tools.builtins.task_tool``.
"""

from __future__ import annotations

import contextvars
from typing import Any

from langchain.tools import BaseTool, ToolRuntime, tool

from agent_sdk.subagents.executor import (
    RunSubagent,
    SubagentExecutor,
    SubagentStatus,
)
from agent_sdk.subagents.registry import SubagentRegistry

# ── Parent-state forwarding context variable ──────────────────────────────
# Set by the task tool before each subagent execution, read by the
# downstream :class:`SubagentRunner` so the subagent's sandbox tools
# operate in the same workspace as the parent agent.
PARENT_STATE_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "subagent_parent_state", default=None
)


def _build_subagent_field_description(registry: SubagentRegistry) -> str:
    """Build the ``subagent_type`` parameter description dynamically from the registry.

    This ensures the LLM sees all available subagent roles with their
    descriptions in the tool's JSON Schema, rather than just a static
    ``(e.g. "general-purpose", "bash")`` hint.
    """
    names = registry.list_names()
    if not names:
        return "The type of subagent to use. No subagent types are currently registered."

    lines = ["The type of subagent to use. Available types:"]
    for name in names:
        definition = registry.get(name)
        if definition is None:
            continue
        # Use the first line of description as a one-line summary.
        desc_first_line = definition.description.strip().split("\n")[0]
        lines.append(f"  - {name}: {desc_first_line}")
    return "\n".join(lines)


def _forward_parent_state(state: dict[str, Any]) -> None:
    """Set the parent-state context for the current subagent call."""
    PARENT_STATE_CTX.set(state)


def _clear_parent_state() -> None:
    """Clear the parent-state context after the subagent call."""
    PARENT_STATE_CTX.set(None)


def make_task_tool(
    tool_name: str = "task",
    *,
    registry: SubagentRegistry | None = None,
    run_subagent: RunSubagent | None = None,
    timeout_seconds: float = 900,
    max_concurrent: int = 3,
) -> BaseTool:
    """Create a ``task`` tool.

    Args:
        tool_name: The name registered with the LLM. Default
            ``"task"``.
        registry: The :class:`SubagentRegistry` to look up roles
            in.  Required for the tool to function; if ``None``
            the tool will return an error for every invocation.
        run_subagent: Callable that executes a subagent task.
            Required for the tool to function; if ``None`` the
            tool will return an error.
        timeout_seconds: Maximum execution time per subagent.
        max_concurrent: Maximum number of concurrent subagents
            (clamped to ``[2, 4]``).
    """

    # Clamp concurrency
    max_concurrent = max(2, min(max_concurrent, 4))

    @tool(tool_name, parse_docstring=True)
    def task(
        description: str,
        prompt: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str:
        """Delegate a subtask to a subagent.

        Args:
            description: A short (3-5 word) description of the task
                for logging/display.
            prompt: The task description for the subagent. Be
                specific and clear about what needs to be done.
            subagent_type: The type of subagent to use (e.g.
                ``"general-purpose"``, ``"bash"``).
        """
        if registry is None or run_subagent is None:
            return (
                "Error: task tool is not configured. "
                "Provide `registry` and `run_subagent` to `make_task_tool`."
            )

        # Validate subagent type
        definition = registry.get(subagent_type)
        if definition is None:
            available = ", ".join(registry.list_names())
            return (
                f"Error: Unknown subagent type {subagent_type!r}. "
                f"Available: {available}"
            )

        # Forward parent state (thread_data / sandbox) to the subagent
        # runner so the subagent's tool calls resolve paths in the same
        # workspace as the parent agent.
        parent_state = dict(runtime.state) if runtime.state is not None else {}

        # Also forward the thread_id from the parent's config so the
        # subagent can acquire/reuse the same sandbox even when the
        # parent hasn't called any sandbox tools yet.
        if runtime.config:
            thread_id = runtime.config.get("configurable", {}).get("thread_id")
            if thread_id:
                parent_state["_thread_id"] = thread_id

        # Fallback: extract from thread_data.workspace_path.
        if not parent_state.get("_thread_id"):
            thread_data = runtime.state.get("thread_data") if runtime.state else None
            if thread_data:
                from agent_sdk.utils.thread import extract_thread_id
                tid = extract_thread_id(thread_data)
                if tid:
                    parent_state["_thread_id"] = tid

        _forward_parent_state(parent_state)

        executor = SubagentExecutor(
            registry=registry,
            run_subagent=run_subagent,
            timeout_seconds=timeout_seconds,
        )

        try:
            result = executor.execute(prompt, subagent_type=subagent_type)
        except Exception as exc:
            return (
                f"Error: failed to launch subagent '{subagent_type}': {exc}. "
                "Do NOT retry — this is an infrastructure failure, not a task failure."
            )
        finally:
            _clear_parent_state()

        if result.status == SubagentStatus.COMPLETED:
            output = result.result or "(no output)"
            return f"Task completed. Result:\n{output}"
        elif result.status == SubagentStatus.FAILED:
            return (
                f"Task failed. Subagent '{subagent_type}' error: {result.error}. "
                "If this is a recursion-limit or timeout error, the task is too "
                "complex — simplify or split it instead of retrying."
            )
        elif result.status == SubagentStatus.TIMED_OUT:
            return (
                f"Task timed out. Subagent '{subagent_type}' error: {result.error}. "
                "Do NOT retry — the task is too large for the subagent's time budget."
            )
        else:
            return f"Task ended with status: {result.status.value}"

    # ── Dynamically inject subagent role descriptions into the tool schema ──
    # Without this, the LLM only sees a static hint like
    # ``(e.g. "general-purpose", "bash")`` and has no knowledge of
    # custom roles registered at startup (skill-scaffolder, etc.).
    if registry is not None:
        _inject_subagent_descriptions(task, registry)

    return task


def _inject_subagent_descriptions(tool_obj: BaseTool, registry: SubagentRegistry) -> None:
    """Overwrite the ``subagent_type`` field description in *tool_obj*'s JSON Schema.

    Called once at tool-creation time so the dynamic description is
    frozen into the schema that gets sent to the LLM on every request.
    """
    schema_cls = tool_obj.args_schema
    if schema_cls is None:
        return
    field_info = schema_cls.model_fields.get("subagent_type")
    if field_info is None:
        return
    field_info.description = _build_subagent_field_description(registry)
