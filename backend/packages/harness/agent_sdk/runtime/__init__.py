"""Runtime package: the SDK's agent-factory surface.

This package hosts the public entry points the SDK exposes to
downstream callers:

* :class:`RuntimeFeatures` — declarative feature flags that
  control which middlewares the factory injects.
* :func:`Next` / :func:`Prev` — class decorators that pin a
  middleware to a position relative to another middleware in
  the chain.
* :class:`ThreadState` — the brand-neutral base state schema
  the factory passes to langgraph.
* :func:`create_agent` — the factory that assembles a
  :class:`langgraph.graph.state.CompiledStateGraph` from a chat
  model, tools, and a feature/middleware configuration.

Submodules
----------
* :mod:`agent_sdk.runtime.user_context` — request-scoped user
  context (ContextVar + ``CurrentUser`` Protocol) used by
  business code for per-user isolation.
* :mod:`agent_sdk.runtime.stream_bridge` — abstract bridge
  between agent workers (producers) and SSE endpoints
  (consumers).

Why this package?
    These primitives are what every product built on top of the
    SDK has to touch. They live at the SDK-entry seam: they
    know about langgraph, but they do **not** know about
    DeerFlow's paths, prompts, audit policy, or subagent
    catalogue. Brand-specific behaviour is injected at
    construction time via the :class:`RuntimeFeatures` flag
    pattern and the :class:`PathProvider` / :class:`MemorySchema`
    / :class:`AuditRules` Protocols (the business / feature layer
    abstractions introduced in stages 1-3).
"""

from agent_sdk.runtime.decorators import Next, Prev
from agent_sdk.runtime.entry import create_agent
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import (
    MiddlewareChainConfig,
    assemble_chain,
)
from agent_sdk.runtime.stream_bridge import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    MemoryStreamBridge,
    StreamBridge,
    StreamEvent,
)
from agent_sdk.runtime.thread_state import ThreadState
from agent_sdk.runtime.user_context import (
    AUTO,
    DEFAULT_USER_ID,
    CurrentUser,
    get_current_user,
    get_effective_user_id,
    require_current_user,
    reset_current_user,
    resolve_user_id,
    set_current_user,
)

__all__ = [
    # entry / features / state
    "Next",
    "Prev",
    "RuntimeFeatures",
    "ThreadState",
    "create_agent",
    # middleware chain assembly
    "MiddlewareChainConfig",
    "assemble_chain",
    # user context
    "AUTO",
    "CurrentUser",
    "DEFAULT_USER_ID",
    "get_current_user",
    "get_effective_user_id",
    "require_current_user",
    "reset_current_user",
    "resolve_user_id",
    "set_current_user",
    # stream bridge
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "MemoryStreamBridge",
    "StreamBridge",
    "StreamEvent",
]
