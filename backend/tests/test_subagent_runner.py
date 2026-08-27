"""Tests for :class:`app.core.subagent_runner.SubagentRunner`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_sdk.subagents.definition import SubagentDefinition
from agent_sdk.subagents.executor import SubagentResult
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import BaseTool

from app.core.subagent_runner import DEFAULT_DISALLOWED, SubagentRunner

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_definition(**overrides) -> SubagentDefinition:
    """Build a SubagentDefinition with defaults overridden."""
    defaults = {
        "name": "test-role",
        "description": "A test role",
        "system_prompt": "You are a test agent.",
    }
    defaults.update(overrides)
    return SubagentDefinition(**defaults)


def _make_echo_tool(name: str = "echo") -> BaseTool:
    """Create a simple tool with the given name."""
    from langchain_core.tools import tool as tool_dec

    @tool_dec(name)
    def _echo(text: str) -> str:
        """Echo input."""
        return text

    return _echo


# ── Tool filtering ─────────────────────────────────────────────────────────


class TestToolFiltering:
    def test_inherits_all_tools_when_allowlist_is_none(self) -> None:
        """tools=None → inherit all parent tools."""
        tools = [_make_echo_tool("a"), _make_echo_tool("b"), _make_echo_tool("c")]
        runner = SubagentRunner(FakeListChatModel(responses=["ok"]), tools)
        definition = _make_definition(tools=None)

        # Patch _lc_create_agent to capture the tools passed
        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("do something", definition)

            _args, kwargs = mock_create.call_args
            passed_tools = kwargs.get("tools") or _args[1]
            tool_names = {t.name for t in passed_tools}
            assert tool_names == {"a", "b", "c"}

    def test_allowlist_filters_tools(self) -> None:
        """Explicit allow-list → only those tools are passed."""
        tools = [_make_echo_tool("a"), _make_echo_tool("b"), _make_echo_tool("c")]
        runner = SubagentRunner(FakeListChatModel(responses=["ok"]), tools)
        definition = _make_definition(tools=["a", "c"])

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("do something", definition)

            _args, kwargs = mock_create.call_args
            passed_tools = kwargs.get("tools") or _args[1]
            tool_names = {t.name for t in passed_tools}
            assert tool_names == {"a", "c"}

    def test_disallowed_tools_are_excluded(self) -> None:
        """Tools in disallowed_tools are removed, including defaults."""
        tools = [
            _make_echo_tool("a"),
            _make_echo_tool("task"),
            _make_echo_tool("ask_clarification"),
        ]
        runner = SubagentRunner(FakeListChatModel(responses=["ok"]), tools)
        definition = _make_definition(tools=None, disallowed_tools=None)

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("do something", definition)

            _args, kwargs = mock_create.call_args
            passed_tools = kwargs.get("tools") or _args[1]
            tool_names = {t.name for t in passed_tools}
            # 'task' and 'ask_clarification' are in DEFAULT_DISALLOWED
            assert tool_names == {"a"}

    def test_custom_disallowed_merges_with_defaults(self) -> None:
        """Custom disallowed_tools are merged with DEFAULT_DISALLOWED."""
        tools = [
            _make_echo_tool("a"),
            _make_echo_tool("task"),
            _make_echo_tool("my_custom"),
        ]
        runner = SubagentRunner(FakeListChatModel(responses=["ok"]), tools)
        definition = _make_definition(
            tools=None, disallowed_tools=["my_custom"]
        )

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("do something", definition)

            _args, kwargs = mock_create.call_args
            passed_tools = kwargs.get("tools") or _args[1]
            tool_names = {t.name for t in passed_tools}
            # 'task' from defaults, 'my_custom' from definition
            assert tool_names == {"a"}

    def test_unknown_tool_in_allowlist_is_skipped(self) -> None:
        """Unknown tool names in allow-list are silently skipped."""
        tools = [_make_echo_tool("a")]
        runner = SubagentRunner(FakeListChatModel(responses=["ok"]), tools)
        definition = _make_definition(tools=["a", "nonexistent"])

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("do something", definition)

            _args, kwargs = mock_create.call_args
            passed_tools = kwargs.get("tools") or _args[1]
            tool_names = {t.name for t in passed_tools}
            assert tool_names == {"a"}


# ── Model resolution ───────────────────────────────────────────────────────


class TestModelResolution:
    def test_inherit_uses_parent_model(self) -> None:
        """definition.model='inherit' → parent model passed to agent."""
        parent_model = FakeListChatModel(responses=["ok"])
        runner = SubagentRunner(parent_model, [])
        definition = _make_definition(model="inherit")

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="done")]}
            mock_create.return_value = mock_agent

            runner("task", definition)

            _args, kwargs = mock_create.call_args
            assert kwargs.get("model") or _args[0] is parent_model


# ── Execution ──────────────────────────────────────────────────────────────


class TestExecution:
    def test_returns_final_ai_content(self) -> None:
        """The last AI message content is returned."""
        parent_model = FakeListChatModel(responses=["ignored"])
        definition = _make_definition()

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {
                "messages": [
                    MagicMock(type="human", content="do something"),
                    MagicMock(type="ai", content="I'll do it."),
                    MagicMock(type="tool", content="result"),
                    MagicMock(type="ai", content="All done!"),
                ]
            }
            mock_create.return_value = mock_agent

            result = SubagentRunner(parent_model, [])( "task", definition)
            assert result == "All done!"

    def test_skips_non_ai_messages(self) -> None:
        """Only AI messages are considered for the final output."""
        parent_model = FakeListChatModel(responses=["ignored"])

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {
                "messages": [
                    MagicMock(type="human", content="task"),
                    MagicMock(type="tool", content="tool output"),
                ]
            }
            mock_create.return_value = mock_agent

            result = SubagentRunner(parent_model, [])( "task", _make_definition())
            assert result is None

    def test_exception_returns_none(self) -> None:
        """If agent creation/invocation raises, None is returned."""
        parent_model = FakeListChatModel(responses=["ignored"])

        with patch("app.core.subagent_runner._lc_create_agent", side_effect=RuntimeError("BOOM")):
            result = SubagentRunner(parent_model, [])( "task", _make_definition())
            assert result is None

    def test_empty_messages_returns_none(self) -> None:
        """Empty message list → None."""
        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": []}
            mock_create.return_value = mock_agent

            result = SubagentRunner(FakeListChatModel(responses=["ignored"]), [])(
                "task", _make_definition()
            )
            assert result is None


# ── System prompt ──────────────────────────────────────────────────────────


class TestSystemPrompt:
    def test_system_prompt_is_passed_to_agent(self) -> None:
        """The definition's system_prompt is used as the agent's system prompt."""
        definition = _make_definition(system_prompt="CUSTOM SYSTEM PROMPT")

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="ok")]}
            mock_create.return_value = mock_agent

            SubagentRunner(FakeListChatModel(responses=["ignored"]), [])(
                "task", definition
            )

            _args, kwargs = mock_create.call_args
            assert kwargs.get("system_prompt") == "CUSTOM SYSTEM PROMPT"


# ── DEFAULT_DISALLOWED ─────────────────────────────────────────────────────


class TestDefaultDisallowed:
    def test_default_disallowed_contains_key_tools(self) -> None:
        """The default disallow list prevents infinite nesting."""
        assert "task" in DEFAULT_DISALLOWED
        assert "ask_clarification" in DEFAULT_DISALLOWED
        assert "present_files" in DEFAULT_DISALLOWED


# ── result_holder compatibility ────────────────────────────────────────────


class TestResultHolder:
    def test_result_holder_is_passed_but_ignored(self) -> None:
        """The result_holder is accepted for protocol compatibility."""
        holder = SubagentResult(task_id="t1", subagent_type="gp")

        with patch("app.core.subagent_runner._lc_create_agent") as mock_create:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [MagicMock(type="ai", content="ok")]}
            mock_create.return_value = mock_agent

            result = SubagentRunner(FakeListChatModel(responses=["ignored"]), [])(
                "task", _make_definition(), holder
            )
            assert result == "ok"
