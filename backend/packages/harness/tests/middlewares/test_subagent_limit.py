"""Unit tests for :class:`agent_sdk.middlewares.SubagentLimitMiddleware`."""

from __future__ import annotations

import pytest
from agent_sdk.middlewares.subagent_limit import (
    DEFAULT_MAX_CONCURRENT,
    MAX_SUBAGENT_LIMIT,
    MIN_SUBAGENT_LIMIT,
    SubagentLimitMiddleware,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

_FAKE_MODEL = FakeListChatModel(responses=["hi"])


def _ai_with_calls(*names: str) -> AIMessage:
    tool_calls = [{"id": f"call-{i}", "name": n, "args": {}} for i, n in enumerate(names)]
    return AIMessage(content="", tool_calls=tool_calls)


def _run(mw: SubagentLimitMiddleware, messages: list) -> ModelResponse:
    """Run one ``wrap_model_call`` round-trip over the given messages."""
    req = ModelRequest(model=_FAKE_MODEL, messages=messages)
    return mw.wrap_model_call(req, lambda r: ModelResponse(result=messages))


# ---------------------------------------------------------------------------
# Clamp behaviour
# ---------------------------------------------------------------------------


class TestClamp:
    def test_default(self) -> None:
        mw = SubagentLimitMiddleware()
        assert mw.max_concurrent == DEFAULT_MAX_CONCURRENT == 3

    @pytest.mark.parametrize("value", [1, 0, -5])
    def test_below_min_clamped_up(self, value: int) -> None:
        mw = SubagentLimitMiddleware(max_concurrent=value)
        assert mw.max_concurrent == MIN_SUBAGENT_LIMIT

    @pytest.mark.parametrize("value", [5, 10, 100])
    def test_above_max_clamped_down(self, value: int) -> None:
        mw = SubagentLimitMiddleware(max_concurrent=value)
        assert mw.max_concurrent == MAX_SUBAGENT_LIMIT

    def test_in_range_preserved(self) -> None:
        for v in (2, 3, 4):
            mw = SubagentLimitMiddleware(max_concurrent=v)
            assert mw.max_concurrent == v


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_no_truncation_when_under_limit(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = _ai_with_calls("task", "task")  # 2 < 3
        result = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        assert result is None

    def test_no_truncation_when_at_limit(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = _ai_with_calls("task", "task", "task")  # == 3
        result = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        assert result is None

    def test_truncation_when_over_limit(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = _ai_with_calls("task", "task", "task", "task", "task")  # 5 > 3
        truncated = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        assert truncated is not None
        kept = [tc["name"] for tc in truncated.tool_calls]
        assert kept == ["task", "task", "task"]

    def test_preserves_non_task_calls(self) -> None:
        # Mix of bash + task; only task should be truncated.
        mw = SubagentLimitMiddleware(max_concurrent=2)
        ai = _ai_with_calls("bash", "task", "bash", "task", "task")
        truncated = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        assert truncated is not None
        kept = [tc["name"] for tc in truncated.tool_calls]
        # 2 task calls kept, bash calls untouched.
        assert kept.count("task") == 2
        assert kept.count("bash") == 2

    def test_first_n_task_calls_kept(self) -> None:
        # Truncation keeps the FIRST N (declaration order), not the last.
        # max_concurrent=2 is the in-range minimum, so no clamping.
        mw = SubagentLimitMiddleware(max_concurrent=2)
        ai = _ai_with_calls("task", "task", "task")
        truncated = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        kept = [tc["name"] for tc in truncated.tool_calls]
        assert kept == ["task", "task"]

    def test_no_tool_calls_returns_none(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = AIMessage(content="hello")
        result = mw._truncate_task_calls_in_message(ai, mw.max_concurrent)
        assert result is None


# ---------------------------------------------------------------------------
# wrap_model_call hooks
# ---------------------------------------------------------------------------


class TestHooks:
    def test_wrap_model_call_truncates(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = _ai_with_calls("task", "task", "task", "task")
        result = _run(mw, [ai])
        assert result is not None
        assert len(result.result[0].tool_calls) == 3

    async def test_awrap_model_call_truncates(self) -> None:
        mw = SubagentLimitMiddleware()
        ai = _ai_with_calls("task", "task", "task", "task", "task")
        req = ModelRequest(model=_FAKE_MODEL, messages=[ai])

        async def handler(r: ModelRequest) -> ModelResponse:
            return ModelResponse(result=[ai])

        result = await mw.awrap_model_call(req, handler)
        assert result is not None
        assert len(result.result[0].tool_calls) == 3
