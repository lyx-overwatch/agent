"""Unit tests for :class:`agent_sdk.middlewares.DanglingToolCallMiddleware`.

Exercises the message-patching logic via the public
``wrap_model_call`` hook, using a small fake handler to
capture the request that is forwarded to the model.
"""

from __future__ import annotations

from typing import Any

from agent_sdk.middlewares.dangling_tool_call import DanglingToolCallMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ai_with_calls(call_id: str, name: str = "bash", args: dict | None = None) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=name, args=args or {"command": "ls"}, id=call_id)],
    )


def _tool_result(call_id: str, content: str = "ok") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name="bash")


# ---------------------------------------------------------------------------
# Construction + static helpers
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_can_construct(self) -> None:
        mw = DanglingToolCallMiddleware()
        assert mw is not None

    def test_message_tool_calls_from_structured(self) -> None:
        msg = _ai_with_calls("call-1", name="read_file", args={"path": "/a"})
        tcs = DanglingToolCallMiddleware._message_tool_calls(msg)
        assert len(tcs) == 1
        assert tcs[0]["id"] == "call-1"
        assert tcs[0]["name"] == "read_file"
        assert tcs[0]["args"] == {"path": "/a"}

    def test_message_tool_calls_from_legacy_kwarg(self) -> None:
        msg = AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "legacy-1",
                        "function": {"name": "bash", "arguments": '{"command":"ls"}'},
                    }
                ]
            },
        )
        tcs = DanglingToolCallMiddleware._message_tool_calls(msg)
        assert len(tcs) == 1
        assert tcs[0]["id"] == "legacy-1"
        assert tcs[0]["name"] == "bash"
        assert tcs[0]["args"] == {"command": "ls"}

    def test_message_tool_calls_ignores_non_dict_raw(self) -> None:
        # Non-dict raw entries must be silently dropped.
        msg = AIMessage(
            content="",
            additional_kwargs={"tool_calls": ["not a dict", {"id": "x", "name": "ok", "args": {}}]},
        )
        tcs = DanglingToolCallMiddleware._message_tool_calls(msg)
        assert len(tcs) == 1
        assert tcs[0]["id"] == "x"

    def test_message_tool_calls_handles_legacy_invalid_json(self) -> None:
        # Invalid JSON in legacy ``arguments`` must not raise.
        msg = AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [
                    {"id": "bad-1", "function": {"name": "bash", "arguments": "not json"}},
                ]
            },
        )
        tcs = DanglingToolCallMiddleware._message_tool_calls(msg)
        assert len(tcs) == 1
        assert tcs[0]["args"] == {}


# ---------------------------------------------------------------------------
# Patching behaviour
# ---------------------------------------------------------------------------


class TestPatching:
    def test_no_patches_when_every_tool_call_has_result(self) -> None:
        mw = DanglingToolCallMiddleware()
        messages = [_ai_with_calls("call-1"), _tool_result("call-1"), HumanMessage(content="done")]
        assert mw._build_patched_messages(messages) is None

    def test_no_patches_when_no_tool_calls(self) -> None:
        mw = DanglingToolCallMiddleware()
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert mw._build_patched_messages(messages) is None

    def test_patches_inserted_after_dangling_ai(self) -> None:
        mw = DanglingToolCallMiddleware()
        messages = [_ai_with_calls("call-1"), HumanMessage(content="user message")]
        patched = mw._build_patched_messages(messages)
        assert patched is not None
        # patched[0] is the original AIMessage, patched[1] is the
        # injected ToolMessage, patched[2] is the human message.
        assert patched[0] is messages[0]
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call-1"
        assert patched[1].status == "error"
        assert "interrupted" in patched[1].content
        assert patched[2] is messages[1]

    def test_patches_preserve_existing_tool_results(self) -> None:
        mw = DanglingToolCallMiddleware()
        # call-1 has a result, call-2 does not.
        messages = [
            _ai_with_calls("call-1"),
            _tool_result("call-1", "result 1"),
            _ai_with_calls("call-2"),
            HumanMessage(content="end"),
        ]
        patched = mw._build_patched_messages(messages)
        assert patched is not None
        # patched[0..2] unchanged; patched[3] is the patch for call-2.
        assert patched[3].tool_call_id == "call-2"
        assert isinstance(patched[3], ToolMessage)
        # patched[4] is the trailing human message.
        assert patched[4] is messages[3]

    def test_each_dangling_id_patched_once(self) -> None:
        mw = DanglingToolCallMiddleware()
        # Two dangling AIMessages with the same call_id (rare but
        # possible); the second occurrence must not re-patch.
        messages = [
            _ai_with_calls("call-1"),
            _ai_with_calls("call-1"),
        ]
        patched = mw._build_patched_messages(messages)
        assert patched is not None
        # patched: AI(1), patch, AI(1) — second AI kept as-is
        # because the id was already patched.
        tool_msgs = [m for m in patched if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "call-1"


# ---------------------------------------------------------------------------
# wrap_model_call / awrap_model_call integration
# ---------------------------------------------------------------------------


class TestWrapModelCall:
    def test_passes_request_through_when_no_dangling(self) -> None:
        mw = DanglingToolCallMiddleware()
        seen_messages: list[Any] = []

        class _Req:
            def __init__(self, msgs: list) -> None:
                self.messages = msgs
                self.tools = []

            def override(self, *, messages=None, tools=None):
                return _Req(messages if messages is not None else self.messages)

        req = _Req([HumanMessage(content="hi")])

        def handler(r):
            seen_messages.append(r.messages)
            return "ok"

        assert mw.wrap_model_call(req, handler) == "ok"
        assert seen_messages[0] is req.messages

    def test_replaces_request_with_patched(self) -> None:
        mw = DanglingToolCallMiddleware()
        seen: list[Any] = []

        class _Req:
            def __init__(self, msgs: list) -> None:
                self.messages = msgs
                self.tools = []

            def override(self, *, messages=None, tools=None):
                new = _Req(messages if messages is not None else self.messages)
                seen.append(new)
                return new

        req = _Req([_ai_with_calls("call-1"), HumanMessage(content="end")])
        mw.wrap_model_call(req, lambda r: "ok")
        # handler should have seen a patched request, not the original.
        assert seen[0].messages is not req.messages
        assert any(isinstance(m, ToolMessage) for m in seen[0].messages)

    def test_async(self) -> None:
        # The async hook should be a thin shim around the sync logic.
        # We use asyncio.run to spin up a fresh event loop; pytest
        # itself is not async.
        import asyncio

        mw = DanglingToolCallMiddleware()
        seen: list[Any] = []

        class _Req:
            def __init__(self, msgs: list) -> None:
                self.messages = msgs
                self.tools = []

            def override(self, *, messages=None, tools=None):
                new = _Req(messages if messages is not None else self.messages)
                seen.append(new)
                return new

        async def handler(r):
            return "ok"

        req = _Req([_ai_with_calls("call-1"), HumanMessage(content="end")])
        result = asyncio.run(mw.awrap_model_call(req, handler))
        assert result == "ok"
        assert any(isinstance(m, ToolMessage) for m in seen[0].messages)
