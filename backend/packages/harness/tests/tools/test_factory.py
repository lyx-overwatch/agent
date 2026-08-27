"""Unit tests for the tool-naming factory pattern.

Verifies the factory abstraction: every built-in tool is created via a
``make_*_tool(tool_name=...)`` factory, and the
``tool_name`` parameter flows into the LLM-facing name registered
with LangChain.
"""

from __future__ import annotations

from agent_sdk.tools import (
    make_ask_clarification_tool,
    make_present_files_tool,
    make_setup_agent_tool,
    make_task_tool,
    make_view_image_tool,
)


class TestAskClarificationTool:
    def test_default_name(self) -> None:
        tool = make_ask_clarification_tool()
        assert tool.name == "ask_clarification"

    def test_custom_name(self) -> None:
        tool = make_ask_clarification_tool(tool_name="clarify_with_user")
        assert tool.name == "clarify_with_user"


class TestPresentFilesTool:
    def test_default_name(self) -> None:
        tool = make_present_files_tool()
        assert tool.name == "present_files"

    def test_custom_name(self) -> None:
        tool = make_present_files_tool(tool_name="show_files")
        assert tool.name == "show_files"


class TestViewImageTool:
    def test_default_name(self) -> None:
        tool = make_view_image_tool()
        assert tool.name == "view_image"

    def test_custom_name(self) -> None:
        tool = make_view_image_tool(tool_name="read_image")
        assert tool.name == "read_image"


class TestTaskTool:
    def test_default_name(self) -> None:
        tool = make_task_tool()
        assert tool.name == "task"

    def test_custom_name(self) -> None:
        tool = make_task_tool(tool_name="delegate")
        assert tool.name == "delegate"


class TestSetupAgentTool:
    def test_default_name(self) -> None:
        tool = make_setup_agent_tool()
        assert tool.name == "setup_agent"

    def test_custom_name(self) -> None:
        tool = make_setup_agent_tool(tool_name="create_subagent")
        assert tool.name == "create_subagent"


class TestAllDefaultNamesMatchDeerFlow:
    """Sanity check: the canonical DeerFlow names are the defaults."""

    def test_all_canonical_names(self) -> None:
        names = {
            make_ask_clarification_tool().name,
            make_present_files_tool().name,
            make_view_image_tool().name,
            make_task_tool().name,
            make_setup_agent_tool().name,
        }
        assert names == {
            "ask_clarification",
            "present_files",
            "view_image",
            "task",
            "setup_agent",
        }
