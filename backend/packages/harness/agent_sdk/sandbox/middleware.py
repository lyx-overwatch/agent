"""SandboxMiddleware — manage a per-thread sandbox lifecycle.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.sandbox_middleware`` and lives
in the sandbox subsystem (rather than the middleware
subsystem) because it is the integration point between the
brand-neutral :class:`SandboxProvider` (stage 5.3) and the
agent runtime.

The middleware:

* acquires a sandbox from the configured provider at agent
  start (or lazily on first tool call when
  ``lazy_init=True``);
* stashes the sandbox id in the ``sandbox`` slot of
  :class:`agent_sdk.runtime.ThreadState`;
* releases the sandbox at agent end (only when the
  middleware owned the acquisition, to avoid double-release
  with other components).

Thread id resolution mirrors :class:`ThreadDataMiddleware`:
``runtime.context["thread_id"]`` first, then
``langgraph.config.get_config()["configurable"]["thread_id"]``.
When neither is set, the middleware is a no-op (the
provider will be asked for a sandbox on the first tool call
that needs one).
"""

from __future__ import annotations

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from agent_sdk.sandbox.base import SandboxProvider
from agent_sdk.utils.thread import resolve_thread_id

logger = logging.getLogger(__name__)


class SandboxMiddlewareState(AgentState):
    """Compatible with the :class:`ThreadState` schema."""

    sandbox: NotRequired[dict | None]


class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    """Acquire / release a per-thread sandbox.

    Args:
        provider: The :class:`SandboxProvider` instance to
            use.  Required — the middleware has no implicit
            default (no globals, no config reads).
        lazy_init: When ``True`` (default), the middleware is
            a no-op in ``before_agent``; the runtime acquires
            a sandbox on the first tool call. When ``False``,
            the sandbox is acquired eagerly at agent start.
    """

    state_schema = SandboxMiddlewareState

    def __init__(self, provider: SandboxProvider, lazy_init: bool = True) -> None:
        super().__init__()
        self._provider = provider
        self._lazy_init = lazy_init

    def _acquire(self, thread_id: str) -> str:
        sandbox_id = self._provider.acquire(thread_id=thread_id)
        logger.info("Acquired sandbox %s for thread %s", sandbox_id, thread_id)
        return sandbox_id

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        if self._lazy_init:
            return super().before_agent(state, runtime)

        # Skip when a sandbox id is already bound.
        if state.get("sandbox"):
            return super().before_agent(state, runtime)

        thread_id = resolve_thread_id(runtime)
        if thread_id is None:
            return super().before_agent(state, runtime)

        sandbox_id = self._acquire(thread_id)
        return {"sandbox": {"sandbox_id": sandbox_id}}

    @override
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # Resident-pool mode: releasing a slot clears it (destructive).  That
        # release must happen only *after* the persister has pulled this turn's
        # files out of the sandbox, so the middleware must NOT release here —
        # the persister's post-run file-sync path owns the release.  We also
        # drop the pool-slot id from state so the next turn re-acquires via the
        # real thread id instead of trying to re-claim a now-unrelated slot.
        if getattr(self._provider, "pool_enabled", False):
            return {"sandbox": None}

        sandbox = state.get("sandbox")
        if sandbox:
            sandbox_id = sandbox.get("sandbox_id")
            if sandbox_id:
                logger.info("Releasing sandbox %s (state-owned)", sandbox_id)
                self._provider.release(sandbox_id)
            return super().after_agent(state, runtime)

        # Sandbox may have been bound via runtime.context instead
        # of state — release it too.
        context_sandbox_id = (runtime.context or {}).get("sandbox_id")
        if context_sandbox_id:
            logger.info("Releasing sandbox %s (context-owned)", context_sandbox_id)
            self._provider.release(context_sandbox_id)
        return super().after_agent(state, runtime)
