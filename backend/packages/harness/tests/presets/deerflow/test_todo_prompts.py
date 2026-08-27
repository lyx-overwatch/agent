"""Unit tests for :mod:`agent_sdk.presets.deerflow.prompts.todo`.

Verifies the re-recorded DeerFlow wording is byte-for-byte
equivalent to the wording the original backend exposes (per
ADR-010's "re-implementation" rule, the constant values are
hand-typed from a behavioural reference rather than imported).
"""

from __future__ import annotations

from agent_sdk.middlewares.todo.middleware import TodoMiddleware
from agent_sdk.middlewares.todo.prompts import TodoPrompts
from agent_sdk.presets.deerflow.prompts.todo import (
    DEERFLOW_TODO_PROMPTS,
    DEERFLOW_TODO_SYSTEM_PROMPT,
    DEERFLOW_TODO_TOOL_DESCRIPTION,
)

# The wording below is what the original ``backend.agents.factory``
# shipped as ``_TODO_SYSTEM_PROMPT`` and ``_TODO_TOOL_DESCRIPTION``.
# The SDK re-records it (per ADR-010) — these constants are the
# source of truth for the byte-level equivalence check.
EXPECTED_SYSTEM_PROMPT = (
    "<todo_list_system>\n"
    "You have access to the `write_todos` tool to help you manage and track complex multi-step objectives.\n"
    "\n"
    "**CRITICAL RULES:**\n"
    "- Mark todos as completed IMMEDIATELY after finishing each step - do NOT batch completions\n"
    "- Keep EXACTLY ONE task as `in_progress` at any time (unless tasks can run in parallel)\n"
    "- Update the todo list in REAL-TIME as you work - this gives users visibility into your progress\n"
    "- DO NOT use this tool for simple tasks (< 3 steps) - just complete them directly\n"
    "</todo_list_system>"
)


EXPECTED_TOOL_DESCRIPTION = (
    "Use this tool to create and manage a structured task list for complex work sessions.  "
    "Only use for complex tasks (3+ steps)."
)


class TestDeerFlowTodoPromptsByteEquivalence:
    def test_system_prompt_is_byte_equivalent(self) -> None:
        assert DEERFLOW_TODO_SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT

    def test_tool_description_is_byte_equivalent(self) -> None:
        # The original backend's tool description has a *double*
        # space between "sessions." and "Only"; preserve it.
        assert DEERFLOW_TODO_TOOL_DESCRIPTION == EXPECTED_TOOL_DESCRIPTION

    def test_double_space_in_tool_description(self) -> None:
        # Defensive check: the double space is intentional and
        # must not be silently collapsed to a single space.
        assert "sessions.  Only" in DEERFLOW_TODO_TOOL_DESCRIPTION


class TestDeerFlowTodoPromptsBundle:
    def test_bundle_uses_deerflow_wording(self) -> None:
        assert DEERFLOW_TODO_PROMPTS.system_prompt == DEERFLOW_TODO_SYSTEM_PROMPT
        assert DEERFLOW_TODO_PROMPTS.tool_description == DEERFLOW_TODO_TOOL_DESCRIPTION

    def test_bundle_is_todo_prompts_dataclass(self) -> None:
        assert isinstance(DEERFLOW_TODO_PROMPTS, TodoPrompts)


class TestDeerFlowPromptsDifferFromDefault:
    def test_deerflow_system_prompt_differs_from_default(self) -> None:
        from agent_sdk.middlewares.todo.prompts import DEFAULT_TODO_SYSTEM_PROMPT

        assert DEERFLOW_TODO_SYSTEM_PROMPT != DEFAULT_TODO_SYSTEM_PROMPT

    def test_deerflow_tool_description_differs_from_default(self) -> None:
        from agent_sdk.middlewares.todo.prompts import DEFAULT_TODO_TOOL_DESCRIPTION

        # The DeerFlow wording has the double-space; the default
        # has a single space.
        assert DEERFLOW_TODO_TOOL_DESCRIPTION != DEFAULT_TODO_TOOL_DESCRIPTION


class TestDeerFlowPromptsInjectableIntoMiddleware:
    def test_middleware_accepts_deerflow_prompts(self) -> None:
        mw = TodoMiddleware(prompts=DEERFLOW_TODO_PROMPTS)
        assert mw.prompts is DEERFLOW_TODO_PROMPTS
        assert "CRITICAL RULES" in mw.prompts.system_prompt

    def test_middleware_default_uses_default_prompts(self) -> None:
        mw = TodoMiddleware()
        assert "CRITICAL RULES" not in mw.prompts.system_prompt
