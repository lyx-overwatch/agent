"""DeerFlow preset: bundles DeerFlow's business choices.

Importing this subpackage gives the caller a ready-made set of
PathProvider / MemorySchema / AuditRules / SubagentRegistry
implementations that preserve the behavior of the original
``backend.packages.harness.deerflow`` package.

The :class:`DeerFlowAgent` convenience class (stage 4) wires
everything together into a single call to
:func:`agent_sdk.runtime.entry.create_agent`.

Usage::

    from agent_sdk.presets.deerflow import DeerFlowAgent

    agent = DeerFlowAgent(model=my_model, plan_mode=True)
    result = await agent.ainvoke({"messages": [...]})
"""

from agent_sdk.presets.deerflow.agent import DEERFLOW_DEFAULT_FEATURES, DeerFlowAgent
from agent_sdk.presets.deerflow.audit import DeerFlowAuditRules
from agent_sdk.presets.deerflow.memory import DeerFlowMemorySchema
from agent_sdk.presets.deerflow.paths import DeerFlowPathProvider
from agent_sdk.presets.deerflow.prompts.system import (
    DEFAULT_AGENT_NAME,
    SYSTEM_PROMPT_TEMPLATE,
    apply_prompt_template,
    build_skills_prompt_section,
    build_subagent_section,
)
from agent_sdk.presets.deerflow.prompts.todo import (
    DEERFLOW_TODO_PROMPTS,
    DEERFLOW_TODO_SYSTEM_PROMPT,
    DEERFLOW_TODO_TOOL_DESCRIPTION,
)
from agent_sdk.presets.deerflow.subagents import DeerFlowSubagentRegistry

__all__ = [
    # Agent
    "DEERFLOW_DEFAULT_FEATURES",
    "DeerFlowAgent",
    # Core presets
    "DeerFlowPathProvider",
    "DeerFlowMemorySchema",
    "DeerFlowSubagentRegistry",
    "DeerFlowAuditRules",
    # Prompts
    "DEFAULT_AGENT_NAME",
    "SYSTEM_PROMPT_TEMPLATE",
    "apply_prompt_template",
    "build_skills_prompt_section",
    "build_subagent_section",
    # Todo
    "DEERFLOW_TODO_PROMPTS",
    "DEERFLOW_TODO_SYSTEM_PROMPT",
    "DEERFLOW_TODO_TOOL_DESCRIPTION",
]
