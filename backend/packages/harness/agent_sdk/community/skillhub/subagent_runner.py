"""SubagentRunner — production-grade ``run_subagent`` implementation.

This module provides :class:`SubagentRunner`, a callable that
implements the SDK's :data:`~agent_sdk.subagents.executor.RunSubagent`
protocol. It takes a subagent task and a
:class:`~agent_sdk.subagents.definition.SubagentDefinition`, filters
the parent's tools, spins up a mini LangGraph ReAct agent, and returns
the final output.

The runner is injected into
:class:`~agent_sdk.runtime.middleware_chain.MiddlewareChainConfig`
alongside a :class:`~agent_sdk.subagents.registry.SubagentRegistry`.

**Parent-state forwarding**: when the subagent is invoked, the parent
agent's ``thread_data`` and ``sandbox`` state are forwarded to the
subagent's initial state so that sandbox tools (write_file, bash, …)
resolve paths in the same workspace as the parent. The state is
transmitted via a :data:`~agent_sdk.tools.task.PARENT_STATE_CTX`
context variable set by the SDK's ``task`` tool before each subagent
execution.

**Cancellation**: :data:`CANCEL_EVENT_CTX` carries a
:class:`threading.Event` from the outer SSE stream into the
synchronous :meth:`SubagentRunner.__call__`. Instead of blocking on
``_future.result(timeout=900)`` the full duration, the runner polls
every ~0.2s so a user's "stop" click is acknowledged almost
immediately.
Set this context variable from the application layer (e.g., in the SSE
stream handler) before the agent loop starts.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent as _lc_create_agent
from langgraph.errors import GraphRecursionError

from agent_sdk.runtime.thread_state import ThreadState
from agent_sdk.tools.task import PARENT_STATE_CTX

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from agent_sdk.subagents.definition import SubagentDefinition
    from agent_sdk.subagents.executor import SubagentResult

logger = logging.getLogger(__name__)

# ── Context variable for cancellation ─────────────────────────────────────
# Set by the application layer (e.g. ChatService.execute_stream) before
# entering the agent loop; read by SubagentRunner.__call__ when polling
# for subagent completion.  Both run in the same asyncio task thread, so
# contextvars propagate correctly.
CANCEL_EVENT_CTX: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar("subagent_cancel_event", default=None)

# ── Polling interval (seconds) for subagent cancellation check ────────────
# A short interval keeps a user's "stop" click responsive while a subagent
# is running — the runner only notices the cancel flag at poll boundaries.
_CANCEL_POLL_INTERVAL: float = 0.2

# ── Always-disallowed tools (prevent infinite nesting / confusion in subagents) ─
DEFAULT_DISALLOWED: list[str] = ["task", "ask_clarification", "present_files"]


class SubagentRunner:
    """Callable runner that executes a subagent task against a real model.

    Each invocation creates a *stateless* mini-agent (no checkpointer),
    runs the task to completion, and returns the final text.

    Args:
        model: The parent agent's chat model (inherited by all
            subagents unless a definition overrides it).
        tools: The full list of tools available to the parent agent.
            Filtered per-invocation based on the subagent
            definition's ``tools`` and ``disallowed_tools`` fields.
        sandbox_provider: Optional sandbox provider. When provided,
            the runner proactively acquires a sandbox for the
            subagent before execution, ensuring sandbox tools
            (write_file, bash, …) can operate in the same workspace
            as the parent agent without relying on runtime config
            propagation.

    Example::

        runner = SubagentRunner(model=my_model, tools=all_tools)
        output = runner("list files in /tmp", definition, result_holder)
    """

    def __init__(
        self,
        model: BaseChatModel,
        tools: list[BaseTool],
        *,
        sandbox_provider: Any | None = None,
        timeout_seconds: float = 900,
    ) -> None:
        self._model = model
        self._all_tools = tools
        self._sandbox_provider = sandbox_provider
        self._timeout = timeout_seconds
        # Fast lookup by name
        self._tool_map: dict[str, BaseTool] = {t.name: t for t in tools}

    def __call__(
        self,
        task: str,
        definition: SubagentDefinition,
        result_holder: SubagentResult | None = None,
    ) -> str | None:
        """Execute *task* using the subagent role described by *definition*.

        Args:
            task: The natural-language task description.
            definition: The subagent role (system prompt, tool
                allow/deny lists, model override, etc.).
            result_holder: Ignored in the sync runner (kept for
                protocol compatibility with
                :data:`~agent_sdk.subagents.executor.RunSubagent`).

        Returns:
            The final text output from the subagent, or ``None``
            if the subagent produced no output.

        Raises:
            ValueError: If *definition* references a parent tool
                that does not exist.
        """
        # ── Resolve model ────────────────────────────────────────────
        model = self._resolve_model(definition)

        # ── Resolve system prompt ────────────────────────────────────
        system_prompt = definition.system_prompt

        # ── Filter tools ─────────────────────────────────────────────
        if definition.tools is not None:
            # Explicit allow-list
            tools = self._filter_by_allowlist(definition.tools)
        else:
            # Inherit all parent tools
            tools = list(self._all_tools)

        # Remove disallowed tools
        disallowed = DEFAULT_DISALLOWED + (definition.disallowed_tools or [])
        tools = [t for t in tools if t.name not in disallowed]

        # ── Forward parent sandbox state ─────────────────────────────
        parent_state = PARENT_STATE_CTX.get() or {}

        # ── Build and run mini-agent ─────────────────────────────────
        try:
            agent = _lc_create_agent(
                model=model,
                tools=tools or None,
                system_prompt=system_prompt,
                state_schema=ThreadState,  # Must use ThreadState so sandbox / thread_data channels are preserved
                # No checkpointer — subagents are stateless
            )

            # Seed the subagent state with the parent's thread_data and
            # sandbox so the subagent's tool calls resolve paths in the
            # same workspace as the parent agent.
            initial_state: dict[str, Any] = {"messages": [{"role": "user", "content": task}]}
            if parent_state.get("thread_data") is not None:
                initial_state["thread_data"] = parent_state["thread_data"]
            if parent_state.get("sandbox") is not None:
                initial_state["sandbox"] = parent_state["sandbox"]

            # ── Resolve the thread_id for sandbox tool access ─────────
            thread_id: str | None = None

            # Source 1 (best): explicit _thread_id forwarded by the task
            # tool from runtime.config["configurable"]["thread_id"].
            thread_id = parent_state.get("_thread_id")

            # Source 2: extract from thread_data workspace path
            # (path format: ".../<thread_id>/workspace").
            if not thread_id:
                thread_data = parent_state.get("thread_data") or {}
                ws = thread_data.get("workspace_path", "")
                if ws:
                    parts = Path(ws).parts
                    if len(parts) >= 2:
                        thread_id = parts[-2]

            # Source 3 (last resort): parent's sandbox_id.
            if not thread_id:
                parent_sandbox = parent_state.get("sandbox") or {}
                sandbox_id = parent_sandbox.get("sandbox_id")
                if sandbox_id and sandbox_id != "local":
                    thread_id = sandbox_id

            # ── Proactively acquire sandbox for the subagent ─────────
            if self._sandbox_provider is not None and thread_id:
                try:
                    sandbox_id = self._sandbox_provider.acquire(thread_id)
                    initial_state["sandbox"] = {"sandbox_id": sandbox_id}
                except Exception:
                    logger.warning(
                        "Failed to pre-acquire sandbox for subagent '%s' (thread_id=%s)",
                        definition.name,
                        thread_id,
                        exc_info=True,
                    )

            # Always set invoke_config with thread_id + recursion_limit.
            # When thread_id is still None (e.g. embedded / test usage),
            # the sandbox tools will fall back to acquiring a new sandbox
            # via _ensure_sandbox → sandbox_provider.acquire(thread_id),
            # which handles None gracefully for local providers.
            # With ThreadState as the state schema, the forwarded sandbox
            # state from the parent is preserved and will be used first
            # by _ensure_sandbox (step 1), so thread_id is only a last
            # resort fallback.
            invoke_config: dict[str, Any] = {
                "configurable": {"thread_id": thread_id} if thread_id else {},
                "recursion_limit": 150,
            }

            # ── Run in an isolated thread to prevent subagent events from
            # leaking into the parent agent's astream_events callback
            # context. Python's ThreadPoolExecutor workers start with an
            # empty contextvars.Context, so LangChain callbacks (which
            # propagate via contextvars) are naturally isolated.
            # Without this isolation, the subagent's internal reasoning
            # tokens, message chunks, and tool calls would be captured by
            # the parent's _collect_step and persisted as hundreds of
            # fragmented database records.
            #
            # Polling with a short timeout instead of a single blocking
            # _future.result(timeout=900) so that user-initiated
            # cancellation (via CANCEL_EVENT_CTX) is acknowledged within
            # ~1 second instead of being ignored until the subagent
            # finishes or hits the 15-minute timeout.
            cancel_event = CANCEL_EVENT_CTX.get()
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="subagent-iso-")
            try:
                # Run the mini-agent asynchronously.  Some tools (notably
                # ``read_skill``) are async-only StructuredTools; invoking the
                # graph synchronously makes LangGraph's ToolNode take the
                # ``_execute_tool_sync`` path, which raises
                # ``NotImplementedError: StructuredTool does not support sync
                # invocation`` for those tools.  ``asyncio.run`` spins up an
                # isolated event loop in this worker thread (which has no
                # running loop), keeping the callback/contextvar isolation the
                # pool was created for.
                _future = _pool.submit(asyncio.run, agent.ainvoke(initial_state, invoke_config))
                deadline = self._timeout
                elapsed: float = 0.0
                result = None

                while True:
                    try:
                        result = _future.result(timeout=_CANCEL_POLL_INTERVAL)
                        break  # completed normally
                    except FuturesTimeoutError:
                        elapsed += _CANCEL_POLL_INTERVAL

                        # User-initiated cancellation — stop waiting and
                        # let the caller (execute_stream) handle cleanup.
                        if cancel_event is not None and cancel_event.is_set():
                            cancel_msg = f"Cancelled by user after {elapsed:.0f}s"
                            logger.info(
                                "Subagent '%s' cancelled by user after %.0fs",
                                definition.name,
                                elapsed,
                            )
                            if result_holder is not None:
                                result_holder.error = cancel_msg
                            return None

                        # Overall timeout guard.
                        if elapsed >= deadline:
                            timeout_msg = f"Timed out after {deadline:.0f}s without completing"
                            logger.error(
                                "Subagent '%s' timed out after %.0fs",
                                definition.name,
                                deadline,
                            )
                            if result_holder is not None:
                                result_holder.error = timeout_msg
                            return None
            finally:
                _pool.shutdown(wait=False, cancel_futures=True)

            # Extract the last AI message content
            messages = result.get("messages", [])
            for msg in reversed(messages):
                content = getattr(msg, "content", None)
                if content and getattr(msg, "type", None) == "ai":
                    return _coerce_to_str(content)

            return None
        except GraphRecursionError:
            error_msg = (
                "Recursion limit exceeded — the subagent ran too many steps "
                "without finishing. The task may be too complex. "
                "Consider breaking it into smaller sub-tasks or simplifying the request."
            )
            logger.error("Subagent '%s' hit recursion limit", definition.name)
            if result_holder is not None:
                result_holder.error = error_msg
            return None
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Subagent '%s' execution failed", definition.name)
            if result_holder is not None:
                result_holder.error = error_msg
            return None

    # ── helpers ───────────────────────────────────────────────────────

    def _resolve_model(self, definition: SubagentDefinition) -> BaseChatModel:
        """Resolve the model for a subagent.

        When *definition.model* is ``"inherit"`` (the default), the
        parent's model is used.  A future iteration may support
        model-per-role via string lookups.
        """
        if definition.model == "inherit":
            return self._model
        # Future: look up by name from a model registry
        logger.warning(
            "Subagent '%s' requested model '%s' — 'inherit' is the only supported mode currently; falling back to parent model.",
            definition.name,
            definition.model,
        )
        return self._model

    def _filter_by_allowlist(self, allowlist: list[str]) -> list[BaseTool]:
        """Filter parent tools to only those named in *allowlist*.

        Unknown names are logged once and skipped — they do not
        halt the subagent.
        """
        tools: list[BaseTool] = []
        seen = self._tool_map
        for name in allowlist:
            if name in seen:
                tools.append(seen[name])
            else:
                logger.warning(
                    "Subagent allow-list references unknown tool '%s' — skipping.",
                    name,
                )
        return tools


def _coerce_to_str(content: str | list) -> str:
    """Normalise langchain message content into a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("data") or ""
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else "(empty response)"
    return str(content) if content else ""
