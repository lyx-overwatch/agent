"""Unit tests for :class:`agent_sdk.middlewares.ToolErrorHandlingMiddleware`.

Exercises the error-coercion behaviour on both the sync and
async hooks. Validates the ``GraphBubbleUp`` re-raise
behaviour (langgraph control flow must survive the wrap).
"""

from __future__ import annotations

import asyncio

import pytest
from agent_sdk.middlewares.tool_error_handling import (
    _MAX_ERROR_DETAIL_LEN,
    ToolErrorHandlingMiddleware,
)
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


def _request(name: str = "bash", call_id: str = "call-1", command: str = "ls") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {"command": command}, "id": call_id, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,
    )


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class TestSync:
    def test_passes_through_on_success(self) -> None:
        mw = ToolErrorHandlingMiddleware()
        ok = ToolMessage(content="ok", tool_call_id="call-1", name="bash")
        result = mw.wrap_tool_call(_request(), lambda req: ok)
        assert result is ok

    def test_converts_exception_to_error_tool_message(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        def handler(req):
            raise RuntimeError("boom")

        result = mw.wrap_tool_call(_request(), handler)
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "call-1"
        assert result.name == "bash"
        assert "RuntimeError" in result.content
        assert "boom" in result.content
        assert "Continue with available context" in result.content

    def test_missing_tool_call_id_uses_fallback(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        def handler(req):
            raise RuntimeError("boom")

        req = _request(call_id="")  # blank id
        result = mw.wrap_tool_call(req, handler)
        assert isinstance(result, ToolMessage)
        # Fallback is the documented ``missing_tool_call_id`` sentinel.
        assert result.tool_call_id == "missing_tool_call_id"

    def test_missing_tool_name_uses_unknown(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        def handler(req):
            raise RuntimeError("boom")

        req = _request(name="")  # blank name
        result = mw.wrap_tool_call(req, handler)
        assert isinstance(result, ToolMessage)
        assert result.name == "unknown_tool"

    def test_long_error_detail_truncated(self) -> None:
        mw = ToolErrorHandlingMiddleware()
        big = "x" * (_MAX_ERROR_DETAIL_LEN * 3)

        def handler(req):
            raise RuntimeError(big)

        result = mw.wrap_tool_call(_request(), handler)
        assert isinstance(result, ToolMessage)
        # The detail is truncated to <= _MAX_ERROR_DETAIL_LEN chars
        # (plus ellipsis).
        # Extract the ``<detail>`` segment between ": " and ". Continue".
        marker = "RuntimeError: "
        idx = result.content.index(marker) + len(marker)
        end = result.content.index(". Continue", idx)
        detail = result.content[idx:end]
        assert len(detail) <= _MAX_ERROR_DETAIL_LEN
        assert detail.endswith("...")

    def test_empty_exception_str_uses_class_name(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        class _EmptyError(RuntimeError):
            def __str__(self) -> str:
                return ""

        def handler(req):
            raise _EmptyError()

        result = mw.wrap_tool_call(_request(), handler)
        assert isinstance(result, ToolMessage)
        assert "_EmptyError" in result.content

    def test_graph_bubble_up_is_preserved(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        def handler(req):
            raise GraphBubbleUp("interrupt!")

        with pytest.raises(GraphBubbleUp, match="interrupt!"):
            mw.wrap_tool_call(_request(), handler)

    def test_value_error_caught(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        def handler(req):
            raise ValueError("bad value")

        result = mw.wrap_tool_call(_request(), handler)
        assert isinstance(result, ToolMessage)
        assert "ValueError" in result.content
        assert "bad value" in result.content


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class TestAsync:
    def test_passes_through_on_success(self) -> None:
        mw = ToolErrorHandlingMiddleware()
        ok = ToolMessage(content="ok", tool_call_id="call-1", name="bash")

        async def handler(req):
            return ok

        result = asyncio.run(mw.awrap_tool_call(_request(), handler))
        assert result is ok

    def test_converts_exception(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        async def handler(req):
            raise RuntimeError("async boom")

        result = asyncio.run(mw.awrap_tool_call(_request(), handler))
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "async boom" in result.content

    def test_graph_bubble_up_is_preserved(self) -> None:
        mw = ToolErrorHandlingMiddleware()

        async def handler(req):
            raise GraphBubbleUp("async interrupt!")

        with pytest.raises(GraphBubbleUp, match="async interrupt!"):
            asyncio.run(mw.awrap_tool_call(_request(), handler))


# ---------------------------------------------------------------------------
# Command return path
# ---------------------------------------------------------------------------


class TestCommandPath:
    def test_command_result_is_passed_through(self) -> None:
        # When the handler returns a Command, the middleware must
        # not attempt to wrap it as a ToolMessage.
        mw = ToolErrorHandlingMiddleware()
        sentinel = Command(update={"messages": []})

        def handler(req):
            return sentinel

        result = mw.wrap_tool_call(_request(), handler)
        assert result is sentinel
