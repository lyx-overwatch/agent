"""StateSizeMonitorMiddleware — monitor agent state data size and warn on bloat.

P0 safety: prevents unbounded state growth from consuming excessive
memory. Each agent loop iteration appends messages (user, assistant,
tool results) to the state. Without monitoring, long-running
conversations with many tool calls can silently exhaust memory.

**What it monitors**

* **Message count** — total number of messages in the state list.
* **Total character count** — sum of all message content lengths.
* **Tool result count** — number of ``ToolMessage`` objects (tool
  outputs are typically the largest single contributor to state bloat).
* **Tool result character count** — sum of ``ToolMessage`` content
  lengths.

**Thresholds (two tiers)**

* **Warn** — log a warning with per-thread metrics. No action taken.
* **Hard** — inject a ``HumanMessage`` asking the agent to
  wrap up and produce a final answer (via
  :class:`ExtendedModelResponse`).

**Per-thread state** is kept in an :class:`OrderedDict` with LRU
eviction so the middleware does not itself become a memory leak.

**Uses** :meth:`wrap_model_call` so it composes into the single
``model`` graph node — **zero** additional recursion_limit steps.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import Command

logger = logging.getLogger(__name__)

# ── Default thresholds ─────────────────────────────────────────────────────
_DEFAULT_WARN_MESSAGE_COUNT = 100
_DEFAULT_HARD_MESSAGE_COUNT = 300
_DEFAULT_WARN_TOTAL_CHARS = 200_000
_DEFAULT_HARD_TOTAL_CHARS = 1_000_000
_DEFAULT_WARN_TOOL_RESULTS = 50
_DEFAULT_HARD_TOOL_RESULTS = 150
_DEFAULT_WARN_TOOL_RESULT_CHARS = 500_000
_DEFAULT_HARD_TOOL_RESULT_CHARS = 2_000_000
_DEFAULT_MAX_TRACKED_THREADS = 200

_WRAP_UP_MESSAGE = (
    "[STATE SIZE WARNING] The conversation state has grown very large "
    "({metric} exceeded the {threshold_name} limit of {threshold_value}). "
    "Stop using tools and produce your final answer now. "
    "Summarize what you have accomplished so far and present your results."
)


# ── Metrics helpers ─────────────────────────────────────────────────────────


def _measure_state(state: dict) -> dict:
    """Measure state size metrics. Returns a dict of metric_name → value."""
    messages = state.get("messages", [])
    total_messages = len(messages)
    total_chars = 0
    tool_results = 0
    tool_result_chars = 0

    for m in messages:
        content = getattr(m, "content", "")
        if isinstance(content, str):
            clen = len(content)
        elif isinstance(content, list):
            clen = sum(len(str(block)) for block in content)
        else:
            clen = len(str(content)) if content else 0

        total_chars += clen

        if isinstance(m, ToolMessage):
            tool_results += 1
            tool_result_chars += clen

    return {
        "total_messages": total_messages,
        "total_chars": total_chars,
        "tool_results": tool_results,
        "tool_result_chars": tool_result_chars,
    }


def _format_size(chars: int) -> str:
    """Human-readable size string."""
    if chars >= 1_000_000:
        return f"{chars / 1_000_000:.1f}M chars"
    if chars >= 1_000:
        return f"{chars / 1_000:.1f}K chars"
    return f"{chars} chars"


# ── Middleware ───────────────────────────────────────────────────────────────


class StateSizeMonitorMiddleware(AgentMiddleware):
    """Monitor agent state size and warn / act on excessive growth.

    Args:
        warn_message_count: Log warning when total messages >= this.  Default: 100.
        hard_message_count: Inject wrap-up message when total messages >= this.  Default: 300.
        warn_total_chars: Log warning when total chars >= this.  Default: 200_000.
        hard_total_chars: Inject wrap-up when total chars >= this.  Default: 1_000_000.
        warn_tool_results: Log warning when tool result count >= this.  Default: 50.
        hard_tool_results: Inject wrap-up when tool result count >= this.  Default: 150.
        warn_tool_result_chars: Log warning when tool result chars >= this.  Default: 500_000.
        hard_tool_result_chars: Inject wrap-up when tool result chars >= this.  Default: 2_000_000.
        max_tracked_threads: LRU cap for per-thread tracking state.  Default: 200.
    """

    def __init__(
        self,
        warn_message_count: int = _DEFAULT_WARN_MESSAGE_COUNT,
        hard_message_count: int = _DEFAULT_HARD_MESSAGE_COUNT,
        warn_total_chars: int = _DEFAULT_WARN_TOTAL_CHARS,
        hard_total_chars: int = _DEFAULT_HARD_TOTAL_CHARS,
        warn_tool_results: int = _DEFAULT_WARN_TOOL_RESULTS,
        hard_tool_results: int = _DEFAULT_HARD_TOOL_RESULTS,
        warn_tool_result_chars: int = _DEFAULT_WARN_TOOL_RESULT_CHARS,
        hard_tool_result_chars: int = _DEFAULT_HARD_TOOL_RESULT_CHARS,
        max_tracked_threads: int = _DEFAULT_MAX_TRACKED_THREADS,
    ) -> None:
        super().__init__()
        self.warn_message_count = warn_message_count
        self.hard_message_count = hard_message_count
        self.warn_total_chars = warn_total_chars
        self.hard_total_chars = hard_total_chars
        self.warn_tool_results = warn_tool_results
        self.hard_tool_results = hard_tool_results
        self.warn_tool_result_chars = warn_tool_result_chars
        self.hard_tool_result_chars = hard_tool_result_chars
        self.max_tracked_threads = max_tracked_threads
        self._lock = threading.Lock()
        # Per-thread peak metrics (LRU eviction).
        self._peaks: OrderedDict[str, dict] = OrderedDict()

    # ------------------------------------------------------------------
    # Thread-id resolution + LRU
    # ------------------------------------------------------------------

    def _get_thread_id(self, request: ModelRequest) -> str:
        # Resolve thread_id (context first, then langgraph config).
        runtime = request.runtime
        thread_id = (runtime.context or {}).get("thread_id") if runtime else None
        if thread_id is None:
            try:
                cfg = get_config()
                thread_id = cfg.get("configurable", {}).get("thread_id")
            except RuntimeError:
                thread_id = None
        return thread_id or "default"

    def _evict_if_needed(self) -> None:
        while len(self._peaks) > self.max_tracked_threads:
            evicted_id, _ = self._peaks.popitem(last=False)
            logger.debug("Evicted state-size tracking for thread %s (LRU)", evicted_id)

    # ------------------------------------------------------------------
    # Detection + action
    # ------------------------------------------------------------------

    def _check_metrics(self, metrics: dict, thread_id: str) -> str | None:
        """Check metrics against thresholds.

        Returns a wrap-up message string if a hard limit is hit, or ``None``.
        Logs warnings for soft thresholds.
        """
        with self._lock:
            if thread_id not in self._peaks:
                self._peaks[thread_id] = {}
                self._evict_if_needed()
            else:
                self._peaks.move_to_end(thread_id)

            peaks = self._peaks[thread_id]

        # Track peaks
        for key in ("total_messages", "total_chars", "tool_results", "tool_result_chars"):
            peaks[key] = max(peaks.get(key, 0), metrics[key])

        # ── Hard limits (return wrap-up message) ──
        threshold_pairs = [
            (metrics["total_messages"], self.hard_message_count, "total_messages", "message count"),
            (metrics["total_chars"], self.hard_total_chars, "total_chars", "total character count"),
            (metrics["tool_results"], self.hard_tool_results, "tool_results", "tool result count"),
            (metrics["tool_result_chars"], self.hard_tool_result_chars, "tool_result_chars", "tool result size"),
        ]
        for current, limit, _key, label in threshold_pairs:
            if current >= limit:
                logger.error(
                    "State size HARD limit reached for thread %s: %s=%s (limit=%s). "
                    "Peaks: messages=%s, chars=%s, tool_results=%s, tool_result_chars=%s",
                    thread_id,
                    label,
                    _format_size(current) if "chars" in _key else str(current),
                    _format_size(limit) if "chars" in _key else str(limit),
                    peaks.get("total_messages", "?"),
                    _format_size(peaks.get("total_chars", 0)),
                    peaks.get("tool_results", "?"),
                    _format_size(peaks.get("tool_result_chars", 0)),
                )
                return _WRAP_UP_MESSAGE.format(
                    metric=label,
                    threshold_name="hard",
                    threshold_value=_format_size(limit) if "chars" in _key else str(limit),
                )

        # ── Soft limits (log warning) ──
        warn_pairs = [
            (metrics["total_messages"], self.warn_message_count, "total_messages", "message count"),
            (metrics["total_chars"], self.warn_total_chars, "total_chars", "total character count"),
            (metrics["tool_results"], self.warn_tool_results, "tool_results", "tool result count"),
            (metrics["tool_result_chars"], self.warn_tool_result_chars, "tool_result_chars", "tool result size"),
        ]
        for current, limit, _key, label in warn_pairs:
            if current >= limit:
                logger.warning(
                    "State size WARNING for thread %s: %s=%s (limit=%s). "
                    "Peaks: messages=%s, chars=%s, tool_results=%s, tool_result_chars=%s",
                    thread_id,
                    label,
                    _format_size(current) if "chars" in _key else str(current),
                    _format_size(limit) if "chars" in _key else str(limit),
                    peaks.get("total_messages", "?"),
                    _format_size(peaks.get("total_chars", 0)),
                    peaks.get("tool_results", "?"),
                    _format_size(peaks.get("tool_result_chars", 0)),
                )
                break  # One warning per iteration is enough.

        return None

    # ------------------------------------------------------------------
    # wrap_model_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse | ExtendedModelResponse:
        response = handler(request)
        return self._apply(request, response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse | ExtendedModelResponse:
        response = await handler(request)
        return self._apply(request, response)

    def _apply(self, request: ModelRequest, response: ModelResponse) -> ModelResponse | ExtendedModelResponse:
        """Measure state size and act on threshold violations."""
        thread_id = self._get_thread_id(request)
        # Skip internal / system threads (e.g. __cache_warm__).
        if thread_id.startswith("__"):
            return response

        state = request.state
        metrics = _measure_state(state)
        wrap_up_msg = self._check_metrics(metrics, thread_id)
        if wrap_up_msg:
            return ExtendedModelResponse(
                model_response=response,
                command=Command(update={"messages": [HumanMessage(content=wrap_up_msg, name="state_size_warning")]}),
            )

        return response

    def reset(self, thread_id: str | None = None) -> None:
        """Clear tracking state. If *thread_id* is given, clear only that thread."""
        with self._lock:
            if thread_id:
                self._peaks.pop(thread_id, None)
            else:
                self._peaks.clear()

    def get_peaks(self, thread_id: str) -> dict:
        """Return peak metrics for *thread_id* (or empty dict if not tracked)."""
        with self._lock:
            return dict(self._peaks.get(thread_id, {}))