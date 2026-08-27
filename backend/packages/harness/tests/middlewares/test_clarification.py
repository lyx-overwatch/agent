"""Unit tests for :class:`agent_sdk.middlewares.ClarificationMiddleware`."""

from __future__ import annotations

from agent_sdk.middlewares.clarification import (
    DEFAULT_CLARIFICATION_TOOL_NAME,
    ClarificationMiddleware,
)
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


def _request(name: str, args: dict, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": call_id, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,
    )


# ---------------------------------------------------------------------------
# Message rendering
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_minimal(self) -> None:
        mw = ClarificationMiddleware()
        out = mw._format_clarification_message({"question": "Which color?"})
        assert "Which color?" in out
        assert "❓" in out  # default icon for missing_info

    def test_with_options(self) -> None:
        mw = ClarificationMiddleware()
        out = mw._format_clarification_message(
            {"question": "Pick a colour", "options": ["red", "blue", "green"]}
        )
        assert "1. red" in out
        assert "2. blue" in out
        assert "3. green" in out

    def test_options_as_json_string(self) -> None:
        # Some models serialise arrays as JSON strings.
        import json

        mw = ClarificationMiddleware()
        out = mw._format_clarification_message(
            {"question": "Pick", "options": json.dumps(["a", "b"])}
        )
        assert "1. a" in out

    def test_options_as_bare_string_fallback(self) -> None:
        mw = ClarificationMiddleware()
        # A bare string is wrapped into a single-item list.
        out = mw._format_clarification_message({"question": "Pick", "options": "only"})
        assert "1. only" in out

    def test_options_none_treated_as_empty(self) -> None:
        mw = ClarificationMiddleware()
        out = mw._format_clarification_message({"question": "Pick", "options": None})
        assert "❓ Pick" in out
        # No numbered options block.
        assert "1." not in out

    def test_custom_type_icon(self) -> None:
        mw = ClarificationMiddleware()
        out = mw._format_clarification_message(
            {"question": "Are you sure?", "clarification_type": "risk_confirmation"}
        )
        assert "⚠️" in out

    def test_context_shown_above_question(self) -> None:
        mw = ClarificationMiddleware()
        out = mw._format_clarification_message(
            {"question": "What scope?", "context": "Background text"}
        )
        assert "Background text" in out
        assert "What scope?" in out
        # Context appears before question.
        assert out.index("Background text") < out.index("What scope?")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


class TestStableMessageId:
    def test_uses_call_id_when_present(self) -> None:
        mw = ClarificationMiddleware()
        msg_id = mw._stable_message_id("call-42", "any content")
        assert msg_id == "clarification:call-42"

    def test_falls_back_to_content_hash(self) -> None:
        mw = ClarificationMiddleware()
        msg_id = mw._stable_message_id("", "deterministic content")
        assert msg_id.startswith("clarification:")
        # Same content → same hash.
        assert mw._stable_message_id("", "deterministic content") == msg_id


# ---------------------------------------------------------------------------
# wrap_tool_call
# ---------------------------------------------------------------------------


class TestWrapToolCall:
    def test_non_clarification_call_passes_through(self) -> None:
        mw = ClarificationMiddleware()
        req = _request("bash", {"command": "ls"})

        def handler(request):
            return ToolMessage(content="ok", tool_call_id="call-1", name="bash")

        result = mw.wrap_tool_call(req, handler)
        assert isinstance(result, ToolMessage)
        assert result.content == "ok"

    def test_clarification_call_returns_command(self) -> None:
        from langgraph.graph import END

        mw = ClarificationMiddleware()
        req = _request(
            DEFAULT_CLARIFICATION_TOOL_NAME,
            {"question": "Which file?", "options": ["a", "b"]},
            call_id="call-c1",
        )
        result = mw.wrap_tool_call(req, lambda r: None)
        assert isinstance(result, Command)
        assert result.goto == END
        # The tool message is added to state.
        new_msg = result.update["messages"][0]
        assert isinstance(new_msg, ToolMessage)
        assert new_msg.tool_call_id == "call-c1"
        assert "Which file?" in new_msg.content
        assert new_msg.name == DEFAULT_CLARIFICATION_TOOL_NAME

    def test_custom_tool_name(self) -> None:
        mw = ClarificationMiddleware(tool_name="ask_user")
        req = _request("ask_user", {"question": "Q?"}, call_id="c1")
        result = mw.wrap_tool_call(req, lambda r: None)
        assert isinstance(result, Command)
        assert result.update["messages"][0].name == "ask_user"

    async def test_async_handler_called_for_non_clarification(self) -> None:
        mw = ClarificationMiddleware()
        req = _request("bash", {"command": "ls"})

        async def async_handler(request):
            return ToolMessage(content="async-ok", tool_call_id="call-1", name="bash")

        result = await mw.awrap_tool_call(req, async_handler)
        assert isinstance(result, ToolMessage)
        assert result.content == "async-ok"

    async def test_async_clarification_short_circuits(self) -> None:
        from langgraph.graph import END

        mw = ClarificationMiddleware()
        req = _request(DEFAULT_CLARIFICATION_TOOL_NAME, {"question": "Q?"}, call_id="c2")
        result = await mw.awrap_tool_call(req, lambda r: None)
        assert isinstance(result, Command)
        assert result.goto == END
