"""LLMErrorHandlingMiddleware — retry transient errors + circuit breaker.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.llm_error_handling_middleware``.

The middleware:

* classifies exceptions into ``transient`` / ``busy`` /
  ``quota`` / ``auth`` / ``generic`` buckets;
* retries on transient / busy errors with exponential
  backoff (capped at ``retry_cap_delay_ms``), honouring
  the provider's ``Retry-After`` / ``Retry-After-Ms`` header
  when present;
* after ``circuit_failure_threshold`` consecutive failures
  the circuit is opened and subsequent calls fail fast
  with a user-facing message, until the
  ``circuit_recovery_timeout_sec`` window elapses;
* emits a stream ``llm_retry`` event for each retry so the
  frontend can show progress;
* preserves LangGraph control-flow signals (``GraphBubbleUp``)
  by re-raising without consuming an attempt.

Configuration is via constructor parameters, not a global
config — the SDK does not read any application config. The
caller (typically the DeerFlow preset) wires the values.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

logger = logging.getLogger(__name__)


#: HTTP status codes the middleware considers transient.
_RETRIABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: Exception class names considered transient. The ``ReadError``
#: and ``RemoteProtocolError`` are httpx exceptions raised when
#: the connection drops mid-stream / is closed unexpectedly.
_TRANSIENT_EXC_NAMES: frozenset[str] = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "ReadError",
        "RemoteProtocolError",
    }
)

#: Keywords that mark a "provider is busy" error. Both English
#: and Chinese patterns are present (the latter is the in-tree
#: reference's set; we keep it for parity).
_BUSY_PATTERNS: tuple[str, ...] = (
    "server busy",
    "temporarily unavailable",
    "try again later",
    "please retry",
    "please try again",
    "overloaded",
    "high demand",
    "rate limit",
    "负载较高",
    "服务繁忙",
    "稍后重试",
    "请稍后重试",
)

#: Keywords that mark a quota / billing / payment error.
_QUOTA_PATTERNS: tuple[str, ...] = (
    "insufficient_quota",
    "quota",
    "billing",
    "credit",
    "payment",
    "余额不足",
    "超出限额",
    "额度不足",
    "欠费",
)

#: Keywords that mark an authentication / authorisation error.
_AUTH_PATTERNS: tuple[str, ...] = (
    "authentication",
    "unauthorized",
    "invalid api key",
    "invalid_api_key",
    "permission",
    "forbidden",
    "access denied",
    "无权",
    "未授权",
)


@dataclass
class CircuitBreakerConfig:
    """Configuration knobs for the circuit breaker.

    Attributes:
        failure_threshold: Number of consecutive failures
            that trip the circuit open. Must be ``>= 1``.
        recovery_timeout_sec: Time the circuit stays open
            before moving to half-open and allowing one
            probe call.
    """

    failure_threshold: int = 5
    recovery_timeout_sec: int = 60


@dataclass
class RetryConfig:
    """Configuration knobs for retry behaviour.

    Attributes:
        max_attempts: Total attempts (including the first
            try). Must be ``>= 1``.
        base_delay_ms: Initial backoff delay.
        cap_delay_ms: Upper bound for the backoff.
    """

    max_attempts: int = 3
    base_delay_ms: int = 1000
    cap_delay_ms: int = 8000


class LLMErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Retry transient LLM errors and surface graceful assistant messages.

    Args:
        retry: :class:`RetryConfig` (or ``None`` for defaults).
        circuit: :class:`CircuitBreakerConfig` (or ``None``
            for defaults).
    """

    def __init__(
        self,
        *,
        retry: RetryConfig | None = None,
        circuit: CircuitBreakerConfig | None = None,
    ) -> None:
        super().__init__()
        self._retry = retry or RetryConfig()
        self._circuit = circuit or CircuitBreakerConfig()

        # Circuit breaker state.
        self._circuit_lock = threading.Lock()
        self._circuit_failure_count = 0
        self._circuit_open_until = 0.0
        self._circuit_state = "closed"  # one of: closed / open / half_open
        self._circuit_probe_in_flight = False

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def _check_circuit(self) -> bool:
        """Return ``True`` if the circuit is OPEN (caller should fast-fail)."""
        with self._circuit_lock:
            now = time.time()
            if self._circuit_state == "open":
                if now < self._circuit_open_until:
                    return True
                self._circuit_state = "half_open"
                self._circuit_probe_in_flight = False
            if self._circuit_state == "half_open":
                if self._circuit_probe_in_flight:
                    return True
                self._circuit_probe_in_flight = True
                return False
            return False

    def _record_success(self) -> None:
        with self._circuit_lock:
            if self._circuit_state != "closed" or self._circuit_failure_count > 0:
                logger.info("Circuit breaker reset (Closed). LLM service recovered.")
            self._circuit_failure_count = 0
            self._circuit_open_until = 0.0
            self._circuit_state = "closed"
            self._circuit_probe_in_flight = False

    def _record_failure(self) -> None:
        with self._circuit_lock:
            if self._circuit_state == "half_open":
                self._circuit_open_until = time.time() + self._circuit.recovery_timeout_sec
                self._circuit_state = "open"
                self._circuit_probe_in_flight = False
                logger.error(
                    "Circuit breaker probe failed (Open). Will probe again after %ds.",
                    self._circuit.recovery_timeout_sec,
                )
                return
            self._circuit_failure_count += 1
            if self._circuit_failure_count >= self._circuit.failure_threshold:
                self._circuit_open_until = time.time() + self._circuit.recovery_timeout_sec
                if self._circuit_state != "open":
                    self._circuit_state = "open"
                    self._circuit_probe_in_flight = False
                    logger.error(
                        "Circuit breaker tripped (Open). Threshold reached (%d). Will probe after %ds.",
                        self._circuit.failure_threshold,
                        self._circuit.recovery_timeout_sec,
                    )

    def _reset_circuit_after_bubble(self) -> None:
        with self._circuit_lock:
            if self._circuit_state == "half_open":
                self._circuit_probe_in_flight = False

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _classify_error(self, exc: BaseException) -> tuple[bool, str]:
        """Return ``(retriable, reason)``."""
        detail = _extract_error_detail(exc).lower()
        error_code = str(_extract_error_code(exc) or "").lower()
        status_code = _extract_status_code(exc)

        if _matches_any(detail, _QUOTA_PATTERNS) or _matches_any(error_code, _QUOTA_PATTERNS):
            return False, "quota"
        if _matches_any(detail, _AUTH_PATTERNS):
            return False, "auth"

        if exc.__class__.__name__ in _TRANSIENT_EXC_NAMES:
            return True, "transient"
        if status_code in _RETRIABLE_STATUS_CODES:
            return True, "transient"
        if _matches_any(detail, _BUSY_PATTERNS):
            return True, "busy"
        return False, "generic"

    def _build_retry_delay_ms(self, attempt: int, exc: BaseException) -> int:
        retry_after = _extract_retry_after_ms(exc)
        if retry_after is not None:
            return retry_after
        backoff = self._retry.base_delay_ms * (2 ** max(0, attempt - 1))
        return min(backoff, self._retry.cap_delay_ms)

    def _build_retry_message(self, attempt: int, wait_ms: int, reason: str) -> str:
        seconds = max(1, round(wait_ms / 1000))
        reason_text = "服务繁忙" if reason == "busy" else "服务暂时不可用"
        return f"正在重试请求 LLM（第 {attempt}/{self._retry.max_attempts} 次）：{reason_text}，{seconds} 秒后重试。"

    def _build_circuit_breaker_message(self) -> str:
        return "LLM 服务因连续失败当前不可用，系统已启用熔断保护。请稍后再试。"

    def _build_user_message(self, exc: BaseException, reason: str) -> str:
        detail = _extract_error_detail(exc)
        if reason == "quota":
            return "LLM 服务账户余额不足或额度受限，请求被拒绝。请检查账户后重试。"
        if reason == "auth":
            return "LLM 服务认证或访问权限无效，请求被拒绝。请检查凭证后重试。"
        if reason in {"busy", "transient"}:
            return "LLM 服务暂时不可用，已多次重试仍失败。请稍后继续对话。"
        return f"LLM 请求失败：{detail}"

    def _build_retry_payload(self, attempt: int, wait_ms: int, reason: str) -> dict[str, Any]:
        return {
            "type": "llm_retry",
            "attempt": attempt,
            "max_attempts": self._retry.max_attempts,
            "wait_ms": wait_ms,
            "reason": reason,
            "message": self._build_retry_message(attempt, wait_ms, reason),
        }

    def _dispatch_retry_event(self, attempt: int, wait_ms: int, reason: str) -> None:
        """Emit a ``llm_retry`` custom event on the sync model path.

        Uses ``dispatch_custom_event`` (langchain-core) instead of langgraph's
        ``get_stream_writer`` — the latter only surfaces when ``astream`` runs
        with ``stream_mode="custom"``, which ``astream_events(version="v2")``
        does not (it defaults to ``values``).  Callback-dispatched custom events
        surface as ``on_custom_event`` regardless of stream mode.
        """
        try:
            from langchain_core.callbacks import dispatch_custom_event

            dispatch_custom_event("llm_retry", self._build_retry_payload(attempt, wait_ms, reason))
        except Exception:
            logger.debug("Failed to emit llm_retry event", exc_info=True)

    async def _adispatch_retry_event(self, attempt: int, wait_ms: int, reason: str) -> None:
        """Async variant of :meth:`_dispatch_retry_event` (async model path)."""
        try:
            from langchain_core.callbacks import adispatch_custom_event

            await adispatch_custom_event("llm_retry", self._build_retry_payload(attempt, wait_ms, reason))
        except Exception:
            logger.debug("Failed to emit llm_retry event", exc_info=True)

    # ------------------------------------------------------------------
    # wrap_model_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        if self._check_circuit():
            return AIMessage(content=self._build_circuit_breaker_message())

        attempt = 1
        while True:
            try:
                response = handler(request)
                self._record_success()
                return response
            except GraphBubbleUp:
                # Preserve LangGraph control-flow signals.
                self._reset_circuit_after_bubble()
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                if retriable and attempt < self._retry.max_attempts:
                    wait_ms = self._build_retry_delay_ms(attempt, exc)
                    logger.warning(
                        "Transient LLM error on attempt %d/%d; retrying in %dms: %s",
                        attempt,
                        self._retry.max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    self._dispatch_retry_event(attempt, wait_ms, reason)
                    time.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                return AIMessage(content=self._build_user_message(exc, reason))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        if self._check_circuit():
            return AIMessage(content=self._build_circuit_breaker_message())

        attempt = 1
        while True:
            try:
                response = await handler(request)
                self._record_success()
                return response
            except GraphBubbleUp:
                self._reset_circuit_after_bubble()
                raise
            except Exception as exc:
                retriable, reason = self._classify_error(exc)
                if retriable and attempt < self._retry.max_attempts:
                    wait_ms = self._build_retry_delay_ms(attempt, exc)
                    logger.warning(
                        "Transient LLM error on attempt %d/%d; retrying in %dms: %s",
                        attempt,
                        self._retry.max_attempts,
                        wait_ms,
                        _extract_error_detail(exc),
                    )
                    await self._adispatch_retry_event(attempt, wait_ms, reason)
                    await asyncio.sleep(wait_ms / 1000)
                    attempt += 1
                    continue
                logger.warning(
                    "LLM call failed after %d attempt(s): %s",
                    attempt,
                    _extract_error_detail(exc),
                    exc_info=exc,
                )
                if retriable:
                    self._record_failure()
                return AIMessage(content=self._build_user_message(exc, reason))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_any(detail: str, patterns: tuple[str, ...]) -> bool:
    return any(p in detail for p in patterns)


def _extract_error_code(exc: BaseException) -> Any:
    for attr in ("code", "error_code"):
        value = getattr(exc, attr, None)
        if value not in (None, ""):
            return value
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("code", "type"):
                value = error.get(key)
                if value not in (None, ""):
                    return value
    return None


def _extract_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _extract_retry_after_ms(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = None
    header_name = ""
    for key in ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After"):
        header_name = key
        if hasattr(headers, "get"):
            raw = headers.get(key)
        if raw:
            break
    if not raw:
        return None
    try:
        multiplier = 1 if "ms" in header_name.lower() else 1000
        return max(0, int(float(raw) * multiplier))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(raw))
            delta = target.timestamp() - time.time()
            return max(0, int(delta * 1000))
        except (TypeError, ValueError, OverflowError):
            return None


def _extract_error_detail(exc: BaseException) -> str:
    detail = str(exc).strip()
    if detail:
        return detail
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return exc.__class__.__name__
