"""Unit tests for :class:`agent_sdk.middlewares.TokenUsageMiddleware`.

Verifies that ``usage_metadata`` is logged (or not) for the
expected message shapes, and that the middleware never mutates
state.
"""

from __future__ import annotations

import logging

from agent_sdk.middlewares.token_usage import TokenUsageMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

_FAKE_MODEL = FakeListChatModel(responses=["hi"])


def _run(mw: TokenUsageMiddleware, messages: list) -> ModelResponse:
    """Run one ``wrap_model_call`` round-trip over the given messages."""
    req = ModelRequest(model=_FAKE_MODEL, messages=messages)
    return mw.wrap_model_call(req, lambda r: ModelResponse(result=messages))


class TestWrapModelCall:
    def test_no_messages_logs_nothing(self, caplog) -> None:
        mw = TokenUsageMiddleware()
        with caplog.at_level(logging.INFO, logger="agent_sdk.middlewares.token_usage"):
            _run(mw, [])
        # No token-usage log line.
        assert not any("LLM token usage" in record.getMessage() for record in caplog.records)

    def test_last_message_without_usage_logs_nothing(self, caplog) -> None:
        mw = TokenUsageMiddleware()
        msg = AIMessage(content="hello")
        with caplog.at_level(logging.INFO, logger="agent_sdk.middlewares.token_usage"):
            _run(mw, [msg])
        # No token-usage log line.
        assert not any("LLM token usage" in record.getMessage() for record in caplog.records)

    def test_last_message_with_usage_logs(self, caplog) -> None:
        mw = TokenUsageMiddleware()
        msg = AIMessage(
            content="hello",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        with caplog.at_level(logging.INFO, logger="agent_sdk.middlewares.token_usage"):
            _run(mw, [msg])
        all_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "LLM token usage" in all_text
        assert "input=100" in all_text
        assert "output=50" in all_text
        assert "total=150" in all_text

    def test_zero_usage_values_logged(self, caplog) -> None:
        # All zero is a valid (if unusual) usage_metadata; the
        # middleware should log it as-is.
        mw = TokenUsageMiddleware()
        msg = AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        with caplog.at_level(logging.INFO, logger="agent_sdk.middlewares.token_usage"):
            _run(mw, [msg])
        all_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "input=0" in all_text
        assert "output=0" in all_text
        assert "total=0" in all_text


class TestAsyncWrapModelCall:
    def test_async_matches_sync(self) -> None:
        import asyncio

        mw = TokenUsageMiddleware()
        msg = AIMessage(
            content="hello",
            usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        )

        async def _go() -> ModelResponse:
            req = ModelRequest(model=_FAKE_MODEL, messages=[msg])

            async def handler(r: ModelRequest) -> ModelResponse:
                return ModelResponse(result=[msg])

            return await mw.awrap_model_call(req, handler)

        sync_result = _run(mw, [msg])
        async_result = asyncio.run(_go())
        # Both paths are observational — they return the response unchanged.
        assert sync_result.result[0].content == "hello"
        assert async_result.result[0].content == "hello"
