"""Subagent subsystem for agent runtime.

Defines the :class:`SubagentDefinition` data class and
:class:`SubagentRegistry` Protocol — the brand-neutral injection
points for subagent (multi-agent) configuration. The SDK ships with
a minimal :class:`DefaultSubagentRegistry` (empty), and the DeerFlow
preset provides :class:`DeerFlowSubagentRegistry` with
``general-purpose`` and ``bash`` built-in roles.
"""

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

__all__ = [
    "SubagentDefinition",
    "SubagentRegistry",
    "DefaultSubagentRegistry",
    "SubagentExecutor",
    "RunSubagent",
    "SubagentResult",
    "SubagentStatus",
    "get_background_task_result",
    "cleanup_background_task",
    "request_cancel_background_task",
]
