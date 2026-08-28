"""Heyu Agent community modules for agent_sdk.

This package provides Heyu Agent's built-in subagent roles and a
reference :class:`~agent_sdk.community.skillhub.subagent_runner.SubagentRunner`
implementation of the SDK's
:data:`~agent_sdk.subagents.executor.RunSubagent` protocol.

Modules:
* :mod:`agent_sdk.community.skillhub.subagent_roles` — Heyu Agent's
  built-in subagent role definitions (general-purpose, bash,
  skill-scaffolder, skill-tester, skill-reviewer)
* :mod:`agent_sdk.community.skillhub.subagent_runner` — Production-grade
  :class:`SubagentRunner` that spins up a mini LangGraph ReAct agent
  for each delegated task
"""

from agent_sdk.community.skillhub.subagent_roles import build_skillhub_registry
from agent_sdk.community.skillhub.subagent_runner import CANCEL_EVENT_CTX, SubagentRunner

__all__ = [
    "CANCEL_EVENT_CTX",
    "SubagentRunner",
    "build_skillhub_registry",
]
