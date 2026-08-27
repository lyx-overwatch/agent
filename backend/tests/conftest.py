"""Shared test fixtures for SkillHub backend tests."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import tool as tool_decorator


@pytest.fixture
def fake_model() -> FakeListChatModel:
    """A chat model that returns a fixed response."""
    return FakeListChatModel(responses=["Task completed successfully."])


@pytest.fixture
def fake_model_multi() -> FakeListChatModel:
    """A chat model with multiple responses for multi-turn subagent flows."""
    return FakeListChatModel(
        responses=[
            # Turn 1: decide to call a tool
            "I'll check that.",
            # Turn 2: final answer after tool result
            "Based on the results, the task is done. Here is the output:\n```\nfile1.txt\nfile2.txt\n```",
        ]
    )


@tool_decorator
def _echo_tool(text: str) -> str:
    """Echo the input back."""
    return text


@tool_decorator
def _add_tool(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool_decorator
def _bash_tool(command: str) -> str:
    """Run a bash command."""
    return f"Executed: {command}"


@pytest.fixture
def sample_tools() -> list[Any]:
    """A representative set of tools for testing tool filtering."""
    return [_echo_tool, _add_tool, _bash_tool]
