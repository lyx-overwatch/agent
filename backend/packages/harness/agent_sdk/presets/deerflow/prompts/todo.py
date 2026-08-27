"""DeerFlow preset: TodoPrompts preserving the original DeerFlow wording.

The two constants in this module re-record (per ADR-010) the
system prompt and tool description that the original
``backend.agents.factory`` module used for its
``_TODO_SYSTEM_PROMPT`` / ``_TODO_TOOL_DESCRIPTION`` constants.
The wording is preserved character-for-character so a
:class:`DeerFlowAgent` constructed from this preset produces
the same LLM-facing contract as the legacy backend.

The brand-neutral default lives in
:mod:`agent_sdk.middlewares.todo.prompts`; use that module
when building a non-DeerFlow product.
"""

from __future__ import annotations

from agent_sdk.middlewares.todo.prompts import TodoPrompts

# Re-recorded from the original ``_TODO_SYSTEM_PROMPT`` constant in
# ``backend.agents.factory``. The wording is preserved so a
# ``DeerFlowAgent`` exposes the same LLM-facing contract as the
# legacy backend.
DEERFLOW_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.

**CRITICAL RULES:**
- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions
- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)
- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress
- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly
</todo_list_system>
""".strip()


# Re-recorded from the original ``_TODO_TOOL_DESCRIPTION`` constant
# in ``backend.agents.factory``. The wording is preserved
# character-for-character (including the double space between
# "sessions." and "Only").
DEERFLOW_TODO_TOOL_DESCRIPTION = "Use this tool to create and manage a structured task list for complex work sessions.  Only use for complex tasks (3+ steps)."


# A ready-to-use :class:`TodoPrompts` populated with the DeerFlow
# wording. Pass it directly to
# :class:`agent_sdk.middlewares.todo.TodoMiddleware` or to a
# future ``DeerFlowAgent`` facade.
DEERFLOW_TODO_PROMPTS: TodoPrompts = TodoPrompts(
    system_prompt=DEERFLOW_TODO_SYSTEM_PROMPT,
    tool_description=DEERFLOW_TODO_TOOL_DESCRIPTION,
)


__all__ = [
    "DEERFLOW_TODO_SYSTEM_PROMPT",
    "DEERFLOW_TODO_TOOL_DESCRIPTION",
    "DEERFLOW_TODO_PROMPTS",
]
