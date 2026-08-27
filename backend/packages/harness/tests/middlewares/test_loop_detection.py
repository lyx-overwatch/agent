"""Unit tests for :class:`agent_sdk.middlewares.LoopDetectionMiddleware`.

Covers the two detection layers (hash-based and
tool-frequency-based), the warning / hard-stop thresholds, the
LRU eviction, and the ``reset`` helper.
"""

from __future__ import annotations

import asyncio

from agent_sdk.middlewares.loop_detection import (
    _HARD_STOP_MSG,
    _WARNING_MSG,
    LoopDetectionMiddleware,
    _hash_tool_calls,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langgraph.runtime import Runtime

_FAKE_MODEL = FakeListChatModel(responses=["hi"])

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _runtime(thread_id: str = "t1") -> Runtime:
    return Runtime(context={"thread_id": thread_id})  # type: ignore[arg-type]


def _ai_with_calls(*calls: tuple[str, str, dict]) -> AIMessage:
    """Build an :class:`AIMessage` carrying the given tool calls.

    Each tuple is ``(call_id, name, args)``.
    """
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=name, args=args, id=call_id) for call_id, name, args in calls],
    )


def _state(last_msg):
    return {"messages": [HumanMessage(content="hi"), last_msg]}


def _request(state: dict, thread_id: str = "t1") -> ModelRequest:
    """Build a :class:`ModelRequest` whose state carries the given messages."""
    return ModelRequest(
        model=_FAKE_MODEL,
        messages=state["messages"],
        state=state,
        runtime=_runtime(thread_id),
    )


def _run(mw: LoopDetectionMiddleware, state: dict, thread_id: str = "t1") -> ModelResponse:
    """Run one ``wrap_model_call`` round-trip for *mw* over *state*."""
    req = _request(state, thread_id)
    return mw.wrap_model_call(req, lambda r: ModelResponse(result=r.state["messages"]))


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


class TestHashToolCalls:
    def test_same_calls_same_hash(self) -> None:
        a = _hash_tool_calls([{"name": "bash", "args": {"command": "ls"}}])
        b = _hash_tool_calls([{"name": "bash", "args": {"command": "ls"}}])
        assert a == b

    def test_different_args_different_hash(self) -> None:
        a = _hash_tool_calls([{"name": "bash", "args": {"command": "ls"}}])
        b = _hash_tool_calls([{"name": "bash", "args": {"command": "ls -la"}}])
        assert a != b

    def test_order_independent(self) -> None:
        a = _hash_tool_calls(
            [
                {"name": "bash", "args": {"command": "ls"}},
                {"name": "read_file", "args": {"path": "/a"}},
            ]
        )
        b = _hash_tool_calls(
            [
                {"name": "read_file", "args": {"path": "/a"}},
                {"name": "bash", "args": {"command": "ls"}},
            ]
        )
        assert a == b

    def test_string_args_handled(self) -> None:
        # ``args`` may be a JSON string from some providers.
        a = _hash_tool_calls([{"name": "bash", "args": '{"command": "ls"}'}])
        b = _hash_tool_calls([{"name": "bash", "args": {"command": "ls"}}])
        assert a == b


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_thresholds(self) -> None:
        mw = LoopDetectionMiddleware()
        assert mw.warn_threshold == 3
        assert mw.hard_limit == 5
        assert mw.window_size == 20
        assert mw.max_tracked_threads == 100
        assert mw.tool_freq_warn == 30
        assert mw.tool_freq_hard_limit == 50

    def test_custom_thresholds(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4, window_size=10, max_tracked_threads=5)
        assert mw.warn_threshold == 2
        assert mw.hard_limit == 4


# ---------------------------------------------------------------------------
# wrap_model_call / awrap_model_call (sync + async)
# ---------------------------------------------------------------------------


class TestWrapModelCall:
    def test_no_messages_returns_unchanged(self) -> None:
        mw = LoopDetectionMiddleware()
        result = _run(mw, {"messages": []})
        assert result.result == []

    def test_last_message_not_ai_returns_unchanged(self) -> None:
        mw = LoopDetectionMiddleware()
        state = {"messages": [HumanMessage(content="hi")]}
        result = _run(mw, state)
        assert result.result == state["messages"]

    def test_no_tool_calls_returns_unchanged(self) -> None:
        mw = LoopDetectionMiddleware()
        state = {"messages": [AIMessage(content="just text")]}
        result = _run(mw, state)
        assert result.result[0].content == "just text"

    def test_warn_injected_after_threshold(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10, window_size=20)
        # Make the same call three times in a row.
        call = ("call-1", "bash", {"command": "ls"})
        result = None
        for _ in range(3):
            result = _run(mw, _state(_ai_with_calls(call)))
        # On the third hit the middleware appends the warning to the AIMessage.
        assert result is not None
        last = result.result[-1]
        assert isinstance(last, AIMessage)
        assert _WARNING_MSG.split("]")[1].strip() in last.content

    def test_warn_only_once_per_hash(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        # 3 hits → first warning.
        _run(mw, _state(_ai_with_calls(call)))
        _run(mw, _state(_ai_with_calls(call)))
        result = _run(mw, _state(_ai_with_calls(call)))
        assert _WARNING_MSG.split("]")[1].strip() in result.result[-1].content
        # 4th hit (count=4) → still in warn range but already warned.
        result2 = _run(mw, _state(_ai_with_calls(call)))
        # No further warning: the dedup key is the hash, not the count.
        assert result2.result[-1].content == ""

    def test_hard_stop_at_limit(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=3, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        _run(mw, _state(_ai_with_calls(call)))
        _run(mw, _state(_ai_with_calls(call)))
        result = _run(mw, _state(_ai_with_calls(call)))
        last = result.result[-1]
        # The patched AIMessage has tool_calls stripped and the
        # _HARD_STOP_MSG appended.
        assert last.tool_calls == []
        assert _HARD_STOP_MSG in last.content

    def test_hard_stop_clears_finish_reason(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=3, window_size=20)

        def _ai():
            # Build an AIMessage with finish_reason="tool_calls"
            # so the middleware has something to flip to "stop".
            msg = _ai_with_calls(("call-1", "bash", {"command": "ls"}))
            msg.response_metadata = {"finish_reason": "tool_calls"}
            return msg

        _run(mw, _state(_ai()))
        _run(mw, _state(_ai()))
        result = _run(mw, _state(_ai()))
        patched = result.result[-1]
        # response_metadata["finish_reason"] must be flipped to "stop".
        assert patched.response_metadata.get("finish_reason") == "stop"

    def test_tool_freq_warning(self) -> None:
        # Use a tiny tool_freq_warn so we don't have to call 30 times.
        mw = LoopDetectionMiddleware(
            warn_threshold=100,  # never trigger via hash
            hard_limit=200,
            tool_freq_warn=3,
            tool_freq_hard_limit=200,
        )
        # Three different calls, same tool name.
        result = None
        for i in range(3):
            call = (f"call-{i}", "read_file", {"path": f"/a/{i}"})
            result = _run(mw, _state(_ai_with_calls(call)))
        # On the third distinct call the freq warning fires.
        assert result is not None
        last = result.result[-1]
        assert isinstance(last, AIMessage)
        assert "read_file 3 times" in last.content

    def test_tool_freq_hard_stop(self) -> None:
        mw = LoopDetectionMiddleware(
            warn_threshold=100,
            hard_limit=200,
            tool_freq_warn=200,
            tool_freq_hard_limit=3,
        )
        result = None
        for i in range(3):
            call = (f"call-{i}", "read_file", {"path": f"/a/{i}"})
            result = _run(mw, _state(_ai_with_calls(call)))
        assert result is not None
        last = result.result[-1]
        assert last.tool_calls == []
        assert "FORCED STOP" in last.content


class TestAsync:
    def test_async_matches_sync(self) -> None:
        # The async hook should produce the same verdict as the
        # sync hook for the same state. We pump a state through
        # ``wrap_model_call`` 3 times then once through
        # ``awrap_model_call`` and confirm the warning fires on the
        # 3rd iteration and is deduplicated on the 4th.
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        results_sync = [_run(mw, _state(_ai_with_calls(call))) for _ in range(3)]

        async def _go() -> ModelResponse:
            req = _request(_state(_ai_with_calls(call)))

            async def handler(r: ModelRequest) -> ModelResponse:
                return ModelResponse(result=r.state["messages"])

            return await mw.awrap_model_call(req, handler)

        result_async = asyncio.run(_go())
        # 3rd hit triggers warn (sync).
        assert _WARNING_MSG.split("]")[1].strip() in results_sync[-1].result[-1].content
        # 4th hit (async) → already warned → unchanged.
        assert result_async.result[-1].content == ""


# ---------------------------------------------------------------------------
# Per-thread isolation + LRU
# ---------------------------------------------------------------------------


class TestThreadIsolation:
    def test_threads_have_independent_state(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        # Two hits on thread A, one on thread B.
        _run(mw, _state(_ai_with_calls(call)), "thread-A")
        result_a = _run(mw, _state(_ai_with_calls(call)), "thread-A")
        result_b = _run(mw, _state(_ai_with_calls(call)), "thread-B")
        # thread A: 2nd hit → warn threshold reached → warning
        assert _WARNING_MSG.split("]")[1].strip() in result_a.result[-1].content
        # thread B: 1st hit → no warning
        assert result_b.result[-1].content == ""

    def test_default_thread_id_when_missing(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})

        def _run_default(state):
            req = ModelRequest(
                model=_FAKE_MODEL,
                messages=state["messages"],
                state=state,
                runtime=Runtime(context={}),  # type: ignore[arg-type]
            )
            return mw.wrap_model_call(req, lambda r: ModelResponse(result=r.state["messages"]))

        # No ``thread_id`` in context → middleware uses the
        # "default" bucket.
        _run_default(_state(_ai_with_calls(call)))
        result = _run_default(_state(_ai_with_calls(call)))
        assert _WARNING_MSG.split("]")[1].strip() in result.result[-1].content

    def test_lru_eviction(self) -> None:
        # max_tracked_threads=2 → adding a 3rd thread evicts the 1st.
        mw = LoopDetectionMiddleware(
            warn_threshold=2, hard_limit=10, window_size=20, max_tracked_threads=2
        )
        call = ("call-1", "bash", {"command": "ls"})
        # Populate threads A and B.
        _run(mw, _state(_ai_with_calls(call)), "A")
        _run(mw, _state(_ai_with_calls(call)), "B")
        # Now add thread C — A should be evicted.
        _run(mw, _state(_ai_with_calls(call)), "C")
        # Build a state and check tracking count.
        assert len(mw._history) == 2
        assert "A" not in mw._history
        assert "B" in mw._history
        assert "C" in mw._history


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_specific_thread(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        _run(mw, _state(_ai_with_calls(call)), "A")
        _run(mw, _state(_ai_with_calls(call)), "B")
        mw.reset("A")
        assert "A" not in mw._history
        assert "B" in mw._history

    def test_reset_all(self) -> None:
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=10, window_size=20)
        call = ("call-1", "bash", {"command": "ls"})
        _run(mw, _state(_ai_with_calls(call)), "A")
        _run(mw, _state(_ai_with_calls(call)), "B")
        mw.reset()
        assert len(mw._history) == 0
