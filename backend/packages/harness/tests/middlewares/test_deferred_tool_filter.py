"""Unit tests for :class:`agent_sdk.middlewares.DeferredToolFilterMiddleware`.

Covers the model-side filter (``wrap_model_call``) and the
tool-side block (``wrap_tool_call``), the no-op behaviour
when no provider is supplied, and the async paths.
"""

from __future__ import annotations

import asyncio

from agent_sdk.middlewares.deferred_tool_filter import _BLOCKED_TOOL_MSG, DeferredToolFilterMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeTool(BaseTool):
    """A minimal :class:`BaseTool` for the test."""

    name: str = "fake"
    description: str = "fake tool"

    def _run(self, **kwargs):  # pragma: no cover - never invoked
        return "ok"


def _request(name: str, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {}, "id": call_id, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,
    )


class _Req:
    """Minimal stand-in for :class:`ModelRequest`."""

    def __init__(self, tools: list) -> None:
        self.tools = tools

    def override(self, *, tools=None, messages=None):
        return _Req(tools if tools is not None else self.tools)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_provider_is_none(self) -> None:
        mw = DeferredToolFilterMiddleware()
        assert mw._provider is None

    def test_custom_provider_is_stored(self) -> None:
        def provider():
            return {"x"}

        mw = DeferredToolFilterMiddleware(deferred_names_provider=provider)
        assert mw._provider is provider


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


class TestNoOpPaths:
    def test_no_provider_model_pass_through(self) -> None:
        mw = DeferredToolFilterMiddleware()
        req = _Req([_FakeTool(name="x"), _FakeTool(name="y")])
        seen: list = []

        def handler(r):
            seen.append(r)
            return "ok"

        result = mw.wrap_model_call(req, handler)
        assert result == "ok"
        # Handler saw the *original* request (no override).
        assert seen[0] is req

    def test_provider_returns_none_model_pass_through(self) -> None:
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: None)
        req = _Req([_FakeTool(name="x")])
        seen: list = []

        def handler(r):
            seen.append(r)
            return "ok"

        result = mw.wrap_model_call(req, handler)
        assert result == "ok"
        assert seen[0] is req

    def test_provider_returns_empty_model_pass_through(self) -> None:
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: set())
        req = _Req([_FakeTool(name="x")])
        seen: list = []

        def handler(r):
            seen.append(r)
            return "ok"

        result = mw.wrap_model_call(req, handler)
        assert result == "ok"
        assert seen[0] is req

    def test_no_provider_tool_pass_through(self) -> None:
        mw = DeferredToolFilterMiddleware()
        called = False

        def handler(req):
            nonlocal called
            called = True
            return ToolMessage(content="ok", tool_call_id="call-1", name="bash")

        result = mw.wrap_tool_call(_request("bash"), handler)
        assert called
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# Model-side filter
# ---------------------------------------------------------------------------


class TestModelFilter:
    def test_removes_deferred_tools(self) -> None:
        deferred = {"deferred_a", "deferred_b"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        tools = [_FakeTool(name="active"), _FakeTool(name="deferred_a"), _FakeTool(name="deferred_b")]
        req = _Req(tools)
        seen: list = []

        def handler(r):
            seen.append(r)
            return "ok"

        mw.wrap_model_call(req, handler)
        # Handler saw a request with only the active tool.
        names = [t.name for t in seen[0].tools]
        assert names == ["active"]

    def test_preserves_order_of_active_tools(self) -> None:
        deferred = {"deferred"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        tools = [
            _FakeTool(name="a"),
            _FakeTool(name="deferred"),
            _FakeTool(name="b"),
            _FakeTool(name="deferred"),
            _FakeTool(name="c"),
        ]
        req = _Req(tools)
        seen: list = []

        def handler(r):
            seen.append(r)
            return "ok"

        mw.wrap_model_call(req, handler)
        names = [t.name for t in seen[0].tools]
        assert names == ["a", "b", "c"]

    def test_async_model_filter(self) -> None:
        deferred = {"deferred"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        tools = [_FakeTool(name="active"), _FakeTool(name="deferred")]
        req = _Req(tools)
        seen: list = []

        async def handler(r):
            seen.append(r)
            return "ok"

        asyncio.run(mw.awrap_model_call(req, handler))
        names = [t.name for t in seen[0].tools]
        assert names == ["active"]


# ---------------------------------------------------------------------------
# Tool-side block
# ---------------------------------------------------------------------------


class TestToolBlock:
    def test_blocks_deferred_tool_call(self) -> None:
        deferred = {"deferred_a"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        called = False

        def handler(req):
            nonlocal called
            called = True
            return ToolMessage(content="ok", tool_call_id="call-1", name="deferred_a")

        result = mw.wrap_tool_call(_request("deferred_a"), handler)
        assert not called
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "call-1"
        assert result.name == "deferred_a"
        assert _BLOCKED_TOOL_MSG in result.content

    def test_allows_active_tool_call(self) -> None:
        deferred = {"deferred_a"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        called = False

        def handler(req):
            nonlocal called
            called = True
            return ToolMessage(content="ok", tool_call_id="call-1", name="active")

        result = mw.wrap_tool_call(_request("active"), handler)
        assert called
        assert result.content == "ok"

    def test_missing_tool_call_id_uses_fallback(self) -> None:
        deferred = {"deferred_a"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        result = mw.wrap_tool_call(_request("deferred_a", call_id=""), lambda req: None)
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "missing_id"

    def test_async_block(self) -> None:
        deferred = {"deferred_a"}
        mw = DeferredToolFilterMiddleware(deferred_names_provider=lambda: deferred)
        called = False

        async def handler(req):
            nonlocal called
            called = True
            return ToolMessage(content="ok", tool_call_id="call-1", name="deferred_a")

        result = asyncio.run(mw.awrap_tool_call(_request("deferred_a"), handler))
        assert not called
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
