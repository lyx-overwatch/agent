"""Unit tests for :class:`agent_sdk.middlewares.todo.TodoPrompts`.

Covers the brand-neutral default and the contract that the
middleware constructor uses.
"""

from __future__ import annotations

import pytest
from agent_sdk.middlewares.todo.prompts import (
    DEFAULT_TODO_SYSTEM_PROMPT,
    DEFAULT_TODO_TOOL_DESCRIPTION,
    TodoPrompts,
)


class TestTodoPromptsDefaults:
    def test_default_system_prompt_mentions_write_todos(self) -> None:
        assert "write_todos" in DEFAULT_TODO_SYSTEM_PROMPT

    def test_default_system_prompt_mentions_3_steps(self) -> None:
        # The default rules mention 3+ steps as the threshold for
        # using the tool.
        assert "3" in DEFAULT_TODO_SYSTEM_PROMPT

    def test_default_tool_description_mentions_write_todos(self) -> None:
        # The default tool description is short; the word
        # "complex" must appear.
        assert "complex" in DEFAULT_TODO_TOOL_DESCRIPTION.lower()

    def test_default_factory_method(self) -> None:
        prompts = TodoPrompts.default()
        assert prompts.system_prompt == DEFAULT_TODO_SYSTEM_PROMPT
        assert prompts.tool_description == DEFAULT_TODO_TOOL_DESCRIPTION


class TestTodoPromptsDataclass:
    def test_construction(self) -> None:
        p = TodoPrompts(system_prompt="X", tool_description="Y")
        assert p.system_prompt == "X"
        assert p.tool_description == "Y"

    def test_frozen(self) -> None:
        p = TodoPrompts(system_prompt="X", tool_description="Y")
        with pytest.raises(Exception):
            p.system_prompt = "Z"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = TodoPrompts(system_prompt="X", tool_description="Y")
        b = TodoPrompts(system_prompt="X", tool_description="Y")
        assert a == b

    def test_inequality(self) -> None:
        a = TodoPrompts(system_prompt="X", tool_description="Y")
        b = TodoPrompts(system_prompt="X", tool_description="Z")
        assert a != b

    def test_default_prompts_are_brand_neutral(self) -> None:
        # The default wording MUST NOT reference DeerFlow, sub-agents,
        # or any product-specific concept.
        for text in (DEFAULT_TODO_SYSTEM_PROMPT, DEFAULT_TODO_TOOL_DESCRIPTION):
            assert "deerflow" not in text.lower()
            assert "sub-agent" not in text.lower()
            assert "subagent" not in text.lower()
