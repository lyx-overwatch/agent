"""LoopDetectionMiddleware — detect and break repetitive tool call loops.

P0 safety: prevents the agent from calling the same tool with
the same arguments indefinitely until the recursion limit
kills the run.

**Detection strategy (two layers)**

1. **Hash-based** (existing in the original backend):
   hash each set of tool calls (name + stable args key),
   track the last *N* hashes in a sliding window per thread.
   When the same hash appears ``warn_threshold`` times, inject
   a "you are repeating yourself — wrap up" system message
   (once per hash). When it appears ``hard_limit`` times,
   strip the ``tool_calls`` from the offending
   :class:`AIMessage` so the agent is forced to produce a
   text answer.

2. **Per-tool-type frequency**: catches the *same tool type*
   being called many times with varying arguments (e.g.
   ``read_file`` on 40 different files). When a single tool
   name has been called ``tool_freq_warn`` times, inject a
   warning. When ``tool_freq_hard_limit``, force-stop.

**Per-thread state** is kept in an :class:`OrderedDict` so the
oldest thread is evicted when ``max_tracked_threads`` is
exceeded (LRU eviction).

**Brand-neutral**: this middleware is pure infrastructure. It
is part of the SDK's always-on chain.

Uses :meth:`wrap_model_call` so it composes into the single
``model`` graph node instead of creating a separate
``after_model`` node — saving 1 recursion_limit step per
iteration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict, defaultdict
from copy import deepcopy
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_config

logger = logging.getLogger(__name__)


# Default thresholds (mirrored from the original backend; see
# the ``__init__`` docstring for the units).
_DEFAULT_WARN_THRESHOLD = 3
_DEFAULT_HARD_LIMIT = 5
_DEFAULT_WINDOW_SIZE = 20
_DEFAULT_MAX_TRACKED_THREADS = 100
_DEFAULT_TOOL_FREQ_WARN = 30
_DEFAULT_TOOL_FREQ_HARD_LIMIT = 50


_WARNING_MSG = (
    "[LOOP DETECTED] You are repeating the same tool calls. "
    "Stop calling tools and produce your final answer now. "
    "If you cannot complete the task, summarize what you accomplished so far."
)

_TOOL_FREQ_WARNING_MSG = (
    "[LOOP DETECTED] You have called {tool_name} {count} times without producing a final answer. "
    "Stop calling tools and produce your final answer now. "
    "If you cannot complete the task, summarize what you accomplished so far."
)

_HARD_STOP_MSG = (
    "[FORCED STOP] Repeated tool calls exceeded the safety limit. "
    "Producing final answer with results collected so far."
)

_TOOL_FREQ_HARD_STOP_MSG = (
    "[FORCED STOP] Tool {tool_name} called {count} times — exceeded the per-tool safety limit. "
    "Producing final answer with results collected so far."
)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def _normalize_tool_call_args(raw_args: object) -> tuple[dict, str | None]:
    """Normalise tool call args to a dict plus an optional fallback key.

    Some providers serialise ``args`` as a JSON string. We
    defensively parse those cases so loop detection does not
    crash while preserving a stable fallback key for
    non-dict payloads.
    """
    if isinstance(raw_args, dict):
        return raw_args, None

    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, raw_args
        if isinstance(parsed, dict):
            return parsed, None
        return {}, raw_args

    return {}, None


def _stable_tool_key(name: str, args: dict, fallback_key: str | None) -> str:
    """Produce a stable, JSON-serialisable key for hashing."""
    try:
        stable_args = {k: args[k] for k in sorted(args.keys())}
        return json.dumps({"name": name, "args": stable_args}, sort_keys=True, default=str)
    except TypeError:
        return json.dumps({"name": name, "args": str(args)}, sort_keys=True, default=str)

    if fallback_key is not None:
        return fallback_key

    return json.dumps(args, sort_keys=True, default=str)


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """Deterministic, order-independent hash of a multiset of tool calls."""
    normalised: list[str] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args, fallback_key = _normalize_tool_call_args(tc.get("args", {}))
        key = _stable_tool_key(name, args, fallback_key)
        normalised.append(f"{name}:{key}")

    normalised.sort()
    blob = json.dumps(normalised, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class LoopDetectionMiddleware(AgentMiddleware):
    """Detect and break repetitive tool call loops.

    Args:
        warn_threshold: Number of identical tool call sets before
            injecting a warning message. Default: 3.
        hard_limit: Number of identical tool call sets before
            stripping ``tool_calls`` entirely. Default: 5.
        window_size: Size of the sliding window for tracking
            calls. Default: 20.
        max_tracked_threads: Maximum number of threads to track
            before evicting the least recently used. Default: 100.
        tool_freq_warn: Number of calls to the same tool *type*
            (regardless of arguments) before injecting a
            frequency warning. Default: 30.
        tool_freq_hard_limit: Number of calls to the same tool
            type before forcing a stop. Default: 50.
    """

    def __init__(
        self,
        warn_threshold: int = _DEFAULT_WARN_THRESHOLD,
        hard_limit: int = _DEFAULT_HARD_LIMIT,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        max_tracked_threads: int = _DEFAULT_MAX_TRACKED_THREADS,
        tool_freq_warn: int = _DEFAULT_TOOL_FREQ_WARN,
        tool_freq_hard_limit: int = _DEFAULT_TOOL_FREQ_HARD_LIMIT,
    ) -> None:
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self.max_tracked_threads = max_tracked_threads
        self.tool_freq_warn = tool_freq_warn
        self.tool_freq_hard_limit = tool_freq_hard_limit
        self._lock = threading.Lock()
        # Per-thread tracking using OrderedDict for LRU eviction.
        self._history: OrderedDict[str, list[str]] = OrderedDict()
        self._warned: dict[str, set[str]] = defaultdict(set)
        # Per-thread, per-tool-type cumulative call counts.
        self._tool_freq: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._tool_freq_warned: dict[str, set[str]] = defaultdict(set)
        # Track the count of "real" user HumanMessages (excluding injected loop_warning)
        # to detect when a new request starts and reset per-request counters.
        self._last_human_msg_count: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Thread-id resolution + LRU bookkeeping
    # ------------------------------------------------------------------

    def _get_thread_id(self, request: ModelRequest) -> str:
        """Extract ``thread_id`` from the runtime context or LangGraph config for per-thread tracking."""
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
        """Evict least-recently-used threads if over the limit.

        Must be called while holding ``self._lock``.
        """
        while len(self._history) > self.max_tracked_threads:
            evicted_id, _ = self._history.popitem(last=False)
            self._warned.pop(evicted_id, None)
            self._tool_freq.pop(evicted_id, None)
            self._tool_freq_warned.pop(evicted_id, None)
            self._last_human_msg_count.pop(evicted_id, None)
            logger.debug("Evicted loop tracking for thread %s (LRU)", evicted_id)

    # ------------------------------------------------------------------
    # Per-request reset
    # ------------------------------------------------------------------

    @staticmethod
    def _count_real_human_messages(messages: list) -> int:
        """Count *real* user HumanMessages, excluding injected loop_warning messages."""
        count = 0
        for m in messages:
            if isinstance(m, HumanMessage) and getattr(m, "name", None) != "loop_warning":
                count += 1
        return count

    def _reset_if_new_request(self, thread_id: str, request: ModelRequest) -> None:
        """Reset per-request counters when a new user message is detected.

        Compares the current HumanMessage count against the last known
        count for *thread_id*.  When it increases, a new user request has
        started and we clear the hash history, warning flags, and
        per-tool-type frequency counters so each request gets its own
        budget.
        """
        messages = request.state.get("messages", [])
        current_count = self._count_real_human_messages(messages)
        last_count = self._last_human_msg_count.get(thread_id, 0)

        if current_count > last_count:
            self._last_human_msg_count[thread_id] = current_count
            self._history.pop(thread_id, None)
            self._warned.pop(thread_id, None)
            self._tool_freq.pop(thread_id, None)
            self._tool_freq_warned.pop(thread_id, None)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _track_and_check(self, request: ModelRequest, tool_calls: list[dict]) -> tuple[str | None, bool]:
        """Track tool calls and check for loops.

        Returns:
            ``(warning_message_or_none, should_hard_stop)``
        """
        thread_id = self._get_thread_id(request)
        call_hash = _hash_tool_calls(tool_calls)

        with self._lock:
            # --- Per-request reset: clear counters on new user message ---
            self._reset_if_new_request(thread_id, request)

            # Touch / create entry (move to end for LRU).
            if thread_id in self._history:
                self._history.move_to_end(thread_id)
            else:
                self._history[thread_id] = []
                self._evict_if_needed()

            history = self._history[thread_id]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size:]

            count = history.count(call_hash)
            tool_names = [tc.get("name", "?") for tc in tool_calls]

            # --- Layer 1: hash-based (identical call sets) ---
            if count >= self.hard_limit:
                logger.error(
                    "Loop hard limit reached — forcing stop",
                    extra={"thread_id": thread_id, "call_hash": call_hash, "count": count, "tools": tool_names},
                )
                return _HARD_STOP_MSG, True

            if count >= self.warn_threshold:
                warned = self._warned[thread_id]
                if call_hash not in warned:
                    warned.add(call_hash)
                    logger.warning(
                        "Repetitive tool calls detected — injecting warning",
                        extra={"thread_id": thread_id, "call_hash": call_hash, "count": count, "tools": tool_names},
                    )
                    return _WARNING_MSG, False

            # --- Layer 2: per-tool-type frequency ---
            freq = self._tool_freq[thread_id]
            for tc in tool_calls:
                name = tc.get("name", "")
                if not name:
                    continue
                freq[name] += 1
                tc_count = freq[name]

                if tc_count >= self.tool_freq_hard_limit:
                    logger.error(
                        "Tool frequency hard limit reached — forcing stop",
                        extra={"thread_id": thread_id, "tool_name": name, "count": tc_count},
                    )
                    return _TOOL_FREQ_HARD_STOP_MSG.format(tool_name=name, count=tc_count), True

                if tc_count >= self.tool_freq_warn:
                    warned = self._tool_freq_warned[thread_id]
                    if name not in warned:
                        warned.add(name)
                        logger.warning(
                            "Tool frequency warning — too many calls to same tool type",
                            extra={"thread_id": thread_id, "tool_name": name, "count": tc_count},
                        )
                        return _TOOL_FREQ_WARNING_MSG.format(tool_name=name, count=tc_count), False

        return None, False

    @staticmethod
    def _append_text(content, text: str):
        """Append *text* to AIMessage content, handling str / list / None.

        When content is a list of content blocks (e.g. Anthropic
        thinking mode), we append a new ``{"type": "text", ...}``
        block instead of concatenating a string to a list, which
        would raise ``TypeError``.
        """
        if content is None:
            return text
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{text}"}]
        if isinstance(content, str):
            return content + f"\n\n{text}"
        return str(content) + f"\n\n{text}"

    @staticmethod
    def _build_hard_stop_update(last_msg: AIMessage, content) -> dict:
        """Clear tool-call metadata so the forced-stop message serialises as plain text."""
        update: dict = {"tool_calls": [], "content": content}

        additional_kwargs = dict(getattr(last_msg, "additional_kwargs", {}) or {})
        for key in ("tool_calls", "function_call"):
            additional_kwargs.pop(key, None)
        update["additional_kwargs"] = additional_kwargs

        response_metadata = deepcopy(getattr(last_msg, "response_metadata", {}) or {})
        if response_metadata.get("finish_reason") == "tool_calls":
            response_metadata["finish_reason"] = "stop"
        update["response_metadata"] = response_metadata

        return update

    # ------------------------------------------------------------------
    # wrap_model_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = handler(request)
        return self._apply(request, response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        response = await handler(request)
        return self._apply(request, response)

    def _apply(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        """Inspect the model response for loop patterns and react accordingly."""
        result = getattr(response, "result", None)
        if not result:
            return response

        # Find the last AIMessage with tool_calls in the response.
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                tool_calls = msg.tool_calls
                warning, hard_stop = self._track_and_check(request, tool_calls)

                if hard_stop:
                    content = self._append_text(msg.content, warning or _HARD_STOP_MSG)
                    stripped_msg = msg.model_copy(update=self._build_hard_stop_update(msg, content))
                    new_result = list(result)
                    new_result[i] = stripped_msg
                    return ModelResponse(
                        result=new_result,
                        structured_response=response.structured_response,
                    )

                if warning:
                    # Append the warning text directly to the AIMessage's
                    # content rather than injecting a separate HumanMessage
                    # via Command(update=…).  A separate message would land
                    # between the AIMessage(tool_calls) and its ToolMessages,
                    # which DeepSeek and other strict providers reject (400).
                    content = self._append_text(msg.content, warning)
                    modified_msg = msg.model_copy(update={"content": content})
                    new_result = list(result)
                    new_result[i] = modified_msg
                    return ModelResponse(
                        result=new_result,
                        structured_response=response.structured_response,
                    )

                break  # Only check the last AI message with tool calls

        return response

    def reset(self, thread_id: str | None = None) -> None:
        """Clear tracking state. If *thread_id* is given, clear only that thread."""
        with self._lock:
            if thread_id:
                self._history.pop(thread_id, None)
                self._warned.pop(thread_id, None)
                self._tool_freq.pop(thread_id, None)
                self._tool_freq_warned.pop(thread_id, None)
                self._last_human_msg_count.pop(thread_id, None)
            else:
                self._history.clear()
                self._warned.clear()
                self._tool_freq.clear()
                self._tool_freq_warned.clear()
                self._last_human_msg_count.clear()