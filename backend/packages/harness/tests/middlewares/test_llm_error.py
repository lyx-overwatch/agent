"""Unit tests for :class:`agent_sdk.middlewares.LLMErrorHandlingMiddleware`."""

from __future__ import annotations

import pytest
from agent_sdk.middlewares.llm_error import (
    CircuitBreakerConfig,
    LLMErrorHandlingMiddleware,
    RetryConfig,
)
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp


def _request() -> ModelRequest:
    return ModelRequest(
        model=None,
        messages=[],
        system_prompt=None,
        tool_choice=None,
        tools=[],
        state={},
        runtime=None,
    )


# ---------------------------------------------------------------------------
# Helpers — fake exceptions
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Stand-in for langchain / openai errors."""

    def __init__(self, message: str, status_code: int | None = None, name: str = "APIError"):
        super().__init__(message)
        self.status_code = status_code
        # __class__.__name__ is what the middleware checks.
        self.__class__.__name__ = name


class _FakeResponse:
    def __init__(self, headers: dict | None = None, status_code: int | None = None):
        self.headers = headers or {}
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_timeout_is_transient(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("timeout", name="APITimeoutError")
        retriable, reason = mw._classify_error(exc)
        assert retriable is True
        assert reason == "transient"

    def test_500_is_transient(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("server error", status_code=500)
        retriable, reason = mw._classify_error(exc)
        assert retriable is True
        assert reason == "transient"

    def test_429_is_transient(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("rate limit", status_code=429)
        retriable, reason = mw._classify_error(exc)
        assert retriable is True
        assert reason == "transient"

    def test_quota_keywords_not_retriable(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("insufficient_quota")
        retriable, reason = mw._classify_error(exc)
        assert retriable is False
        assert reason == "quota"

    def test_auth_keywords_not_retriable(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("invalid api key")
        retriable, reason = mw._classify_error(exc)
        assert retriable is False
        assert reason == "auth"

    def test_busy_phrase_retriable(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("server is currently overloaded")
        retriable, reason = mw._classify_error(exc)
        assert retriable is True
        assert reason == "busy"

    def test_unknown_error_generic(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("weird error")
        retriable, reason = mw._classify_error(exc)
        assert retriable is False
        assert reason == "generic"

    def test_httpx_read_error(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("read failed", name="ReadError")
        retriable, reason = mw._classify_error(exc)
        assert retriable is True
        assert reason == "transient"


# ---------------------------------------------------------------------------
# User message
# ---------------------------------------------------------------------------


class TestUserMessage:
    def test_quota_message(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        msg = mw._build_user_message(_FakeAPIError("quota"), "quota")
        assert "quota" in msg.lower()

    def test_auth_message(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        msg = mw._build_user_message(_FakeAPIError("auth"), "auth")
        assert "authentication" in msg.lower() or "credentials" in msg.lower()

    def test_busy_message(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        msg = mw._build_user_message(_FakeAPIError("busy"), "busy")
        assert "temporarily unavailable" in msg.lower()

    def test_generic_message_includes_detail(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        msg = mw._build_user_message(_FakeAPIError("oh no detail"), "generic")
        assert "oh no detail" in msg


# ---------------------------------------------------------------------------
# Retry backoff
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_exponential(self) -> None:
        mw = LLMErrorHandlingMiddleware(retry=RetryConfig(base_delay_ms=1000, cap_delay_ms=60000))
        assert mw._build_retry_delay_ms(1, _FakeAPIError("x")) == 1000
        assert mw._build_retry_delay_ms(2, _FakeAPIError("x")) == 2000
        assert mw._build_retry_delay_ms(3, _FakeAPIError("x")) == 4000
        assert mw._build_retry_delay_ms(4, _FakeAPIError("x")) == 8000

    def test_capped(self) -> None:
        mw = LLMErrorHandlingMiddleware(retry=RetryConfig(base_delay_ms=1000, cap_delay_ms=3000))
        # attempt 1: 1000; attempt 5: 1000 * 2^4 = 16000, capped to 3000
        assert mw._build_retry_delay_ms(5, _FakeAPIError("x")) == 3000

    def test_retry_after_header_takes_precedence(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        exc = _FakeAPIError("rate limit", status_code=429)
        exc.response = _FakeResponse(headers={"Retry-After-Ms": "5000"})
        assert mw._build_retry_delay_ms(1, exc) == 5000


# ---------------------------------------------------------------------------
# wrap_model_call
# ---------------------------------------------------------------------------


class TestWrapModelCall:
    def test_succeeds_on_first_try(self) -> None:
        mw = LLMErrorHandlingMiddleware()

        def handler(req):
            return AIMessage(content="ok")

        result = mw.wrap_model_call(_request(), handler)
        assert isinstance(result, AIMessage)
        assert result.content == "ok"

    def test_retries_then_succeeds(self) -> None:
        mw = LLMErrorHandlingMiddleware(retry=RetryConfig(max_attempts=3, base_delay_ms=1, cap_delay_ms=1))
        attempts = {"n": 0}

        def handler(req):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise _FakeAPIError("timeout", name="APITimeoutError")
            return AIMessage(content="ok")

        result = mw.wrap_model_call(_request(), handler)
        assert isinstance(result, AIMessage)
        assert result.content == "ok"
        assert attempts["n"] == 2

    def test_exhausts_retries_returns_user_message(self) -> None:
        mw = LLMErrorHandlingMiddleware(retry=RetryConfig(max_attempts=2, base_delay_ms=1, cap_delay_ms=1))

        def handler(req):
            raise _FakeAPIError("timeout", name="APITimeoutError")

        result = mw.wrap_model_call(_request(), handler)
        assert isinstance(result, AIMessage)
        assert "temporarily unavailable" in result.content.lower()

    def test_non_retriable_returns_user_message_immediately(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            raise _FakeAPIError("invalid api key")

        result = mw.wrap_model_call(_request(), handler)
        assert isinstance(result, AIMessage)
        assert "credentials" in result.content.lower() or "authentication" in result.content.lower()
        assert calls["n"] == 1  # no retry

    def test_graph_bubble_up_preserved(self) -> None:
        mw = LLMErrorHandlingMiddleware()
        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            raise GraphBubbleUp()

        with pytest.raises(GraphBubbleUp):
            mw.wrap_model_call(_request(), handler)
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_opens_after_threshold(self) -> None:
        cfg = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_sec=60)
        mw = LLMErrorHandlingMiddleware(circuit=cfg, retry=RetryConfig(max_attempts=1, base_delay_ms=1, cap_delay_ms=1))

        # Two consecutive failures.
        for _ in range(2):
            try:
                mw.wrap_model_call(_request(), lambda r: (_ for _ in ()).throw(_FakeAPIError("timeout", name="APITimeoutError")))
            except Exception:
                pass

        # Now the circuit is open; the next call short-circuits.
        result = mw.wrap_model_call(_request(), lambda r: AIMessage(content="should-not-reach"))
        assert "circuit breaker" in result.content.lower()

    def test_success_resets_circuit(self) -> None:
        cfg = CircuitBreakerConfig(failure_threshold=2, recovery_timeout_sec=60)
        mw = LLMErrorHandlingMiddleware(circuit=cfg, retry=RetryConfig(max_attempts=1, base_delay_ms=1, cap_delay_ms=1))

        # Cause a failure, then a success.
        try:
            mw.wrap_model_call(_request(), lambda r: (_ for _ in ()).throw(_FakeAPIError("timeout", name="APITimeoutError")))
        except Exception:
            pass
        mw.wrap_model_call(_request(), lambda r: AIMessage(content="ok"))

        # The circuit is reset; we can record more failures without
        # short-circuiting until the threshold is hit again.
        try:
            mw.wrap_model_call(_request(), lambda r: (_ for _ in ()).throw(_FakeAPIError("timeout", name="APITimeoutError")))
        except Exception:
            pass
        # One failure, threshold is 2 — should not yet trip.
        result = mw.wrap_model_call(_request(), lambda r: AIMessage(content="ok"))
        assert result.content == "ok"
