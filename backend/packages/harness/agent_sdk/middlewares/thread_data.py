"""ThreadDataMiddleware — create and expose the per-thread data directories.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.thread_data_middleware``.

The middleware populates the ``thread_data`` slot of
:class:`agent_sdk.runtime.ThreadState` with three filesystem
roots: ``workspace_path``, ``uploads_path``, and
``outputs_path``. By default directory creation is **lazy**:
the middleware only computes the paths in ``before_agent`` and
leaves actual ``mkdir`` to whatever tool needs the directory
(e.g. the first ``bash`` invocation, or the first upload).

Why a ``PathProvider`` injection?
    The in-tree reference uses the ``Paths`` global. The SDK
    does not have a global — the runtime constructs a
    :class:`agent_sdk.paths.PathProvider` and threads it
    through. Without an injected provider the middleware
    would need to read a config file, which violates the
    brand-neutral contract.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from agent_sdk.paths.provider import PathProvider
from agent_sdk.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


class ThreadDataMiddlewareState(AgentState):
    """Compatible with the :class:`ThreadState` schema."""

    thread_data: NotRequired[dict | None]


class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Resolve per-thread data directories and expose them in state.

    Args:
        path_provider: Brand-neutral source of per-thread
            paths. Required — the middleware has no
            implicit default (no globals, no config reads).
        lazy_init: When ``True`` (default), only compute
            paths in ``before_agent``; directories are
            created on demand. When ``False``, eagerly
            create the directories on the first
            ``before_agent`` call.
    """

    state_schema = ThreadDataMiddlewareState

    def __init__(self, path_provider: PathProvider, lazy_init: bool = True) -> None:
        super().__init__()
        self._paths = path_provider
        self._lazy_init = lazy_init

    def _get_thread_paths(self, thread_id: str, user_id: str | None = None) -> dict[str, str]:
        return {
            "workspace_path": str(self._paths.get_workspace_dir(thread_id, user_id=user_id)),
            "uploads_path": str(self._paths.get_uploads_dir(thread_id, user_id=user_id)),
            "outputs_path": str(self._paths.get_outputs_dir(thread_id, user_id=user_id)),
        }

    def _create_thread_directories(self, thread_id: str, user_id: str | None = None) -> dict[str, str]:
        # Eagerly ensure the directories exist.  PathProvider does
        # not auto-mkdir — that decision is left to the caller, so
        # the runtime can choose between "fail fast on missing dir"
        # and "auto-create".
        for d in (
            self._paths.get_workspace_dir(thread_id, user_id=user_id),
            self._paths.get_uploads_dir(thread_id, user_id=user_id),
            self._paths.get_outputs_dir(thread_id, user_id=user_id),
        ):
            d.mkdir(parents=True, exist_ok=True)
        return self._get_thread_paths(thread_id, user_id=user_id)

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        context = runtime.context or {}
        thread_id = context.get("thread_id")
        if thread_id is None:
            try:
                cfg = get_config()
                thread_id = cfg.get("configurable", {}).get("thread_id")
            except RuntimeError:
                thread_id = None

        if thread_id is None:
            raise ValueError("Thread ID is required in runtime context or config.configurable")

        user_id = get_effective_user_id()

        if self._lazy_init:
            paths = self._get_thread_paths(thread_id, user_id=user_id)
        else:
            paths = self._create_thread_directories(thread_id, user_id=user_id)
            logger.debug("Created thread data directories for thread %s", thread_id)

        # Stamp the last human message with run metadata so the
        # frontend can show "sent at HH:MM" and the journal can
        # correlate the message with a run id.
        messages = list(state.get("messages", []))
        if messages and isinstance(messages[-1], HumanMessage):
            last = messages[-1]
            messages[-1] = HumanMessage(
                content=last.content,
                id=last.id,
                name=last.name or "user-input",
                additional_kwargs={
                    **last.additional_kwargs,
                    "run_id": context.get("run_id"),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        return {
            "thread_data": dict(paths),
            "messages": messages,
        }
