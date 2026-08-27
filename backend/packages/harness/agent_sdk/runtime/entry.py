"""create_agent — the SDK's public agent-factory entry point.

This is the SDK re-implementation (per ADR-010) of
``deerflow.agents.factory.create_deerflow_agent`` — the
function that sits between the raw
``langchain.agents.create_agent`` primitive and any product
that wants to assemble an agent from a chat model, a list of
tools, and a :class:`RuntimeFeatures` declaration.

The function exposes a single ``create_agent`` entry point
that:

* takes the same parameters as the original
  ``create_deerflow_agent`` (model, tools, system_prompt,
  middleware, features, extra_middleware, state_schema,
  checkpointer, name);
* if ``middleware`` is supplied, uses *exactly* that list
  ("full takeover" mode);
* otherwise, assembles a chain from :class:`RuntimeFeatures`
  and the ``@Next`` / ``@Prev`` anchors carried by any
  ``extra_middleware``;
* deduplicates tool names (user tools win);
* delegates to :func:`langchain.agents.create_agent` for the
  final assembly into a :class:`CompiledStateGraph`.

**Scope of this first batch (5.1)**

The chain assembly includes the always-on universal middlewares
that are always-on (:class:`DanglingToolCallMiddleware`,
:class:`ToolErrorHandlingMiddleware`,
:class:`LoopDetectionMiddleware`). Feature-driven
middlewares (sandbox / memory / summarization / subagent /
vision / auto_title) are scheduled for stage 5.6
and are deliberately *not* wired up here: passing any of those
features as ``True`` raises :class:`NotImplementedError` with
a message pointing at the future stage.

**In other words:** this entry point is fully functional for
the always-on baseline (the universal middlewares). It will be
extended in 5.6 with the feature middlewares, at which
point ``RuntimeFeatures(memory=True, subagent=True, …)`` will
become a complete declarative configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents import create_agent as _lc_create_agent

from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import (
    MiddlewareChainConfig,
    assemble_chain,
)
from agent_sdk.runtime.thread_state import ThreadState

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


def create_agent(
    model: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: list[AgentMiddleware] | None = None,
    features: RuntimeFeatures | None = None,
    extra_middleware: list[AgentMiddleware] | None = None,
    state_schema: type | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    name: str = "default",
    middleware_deps: MiddlewareChainConfig | None = None,
    plan_mode: bool = False,
) -> CompiledStateGraph:
    """Create an SDK agent from plain Python arguments.

    The factory assembly itself reads no config files.  Some
    injected runtime components (e.g. ``summarization_model``)
    may still depend on caller-supplied state at invocation
    time.

    Parameters
    ----------
    model:
        Chat model instance.
    tools:
        User-provided tools.  Feature-injected tools
        (``view_image`` / ``task`` / ``ask_clarification``)
        are appended automatically when the corresponding
        feature is enabled.
    system_prompt:
        System message.  ``None`` uses langchain's default
        (typically a no-op prompt).
    middleware:
        **Full takeover** — if provided, this exact list is used.
        Cannot be combined with *features* or *extra_middleware*.
    features:
        Declarative feature flags.  Cannot be combined with
        *middleware*.
    extra_middleware:
        Additional middlewares inserted into the auto-assembled
        chain via ``@Next`` / ``@Prev`` positioning.  Cannot be
        used with *middleware*.
    state_schema:
        LangGraph state type.  Defaults to :class:`ThreadState`.
    checkpointer:
        Optional persistence backend.
    name:
        Agent name (forwarded to middlewares that care, e.g.
        ``MemoryMiddleware``).
    middleware_deps:
        Runtime dependencies the feature middlewares need
        (paths, sandbox provider, memory schema + storage,
        summarisation model, …).  When *features* enables
        a feature whose dependency is missing, the
        factory raises :class:`ValueError` with a message
        pointing at the missing field.
    plan_mode:
        Enable :class:`TodoMiddleware` for task tracking
        regardless of any feature flag.

    Raises
    ------
    ValueError
        If both *middleware* and *features*/*extra_middleware*
        are provided, or if a feature is enabled but its
        *middleware_deps* dependency is missing.
    TypeError
        If any *extra_middleware* item is not an
        :class:`AgentMiddleware` instance.

    Notes
    -----
    This function is the SDK's re-implementation of
    ``create_deerflow_agent`` (per ADR-010); the parameter
    surface and error contract are preserved so a future
    :class:`DeerFlowAgent` preset can wrap this entry point
    with zero behavioural drift.
    """
    # --- Argument validation (matches create_deerflow_agent) ---
    if middleware is not None and features is not None:
        raise ValueError("Cannot specify both 'middleware' and 'features'. Use one or the other.")
    if middleware is not None and extra_middleware:
        raise ValueError("Cannot use 'extra_middleware' with 'middleware' (full takeover).")
    if extra_middleware:
        from langchain.agents.middleware import AgentMiddleware

        for mw in extra_middleware:
            if not isinstance(mw, AgentMiddleware):
                raise TypeError(
                    f"extra_middleware items must be AgentMiddleware instances, got {type(mw).__name__}"
                )

    effective_tools: list[BaseTool] = list(tools or [])
    effective_state = state_schema or ThreadState

    if middleware is not None:
        # Full-takeover mode: bypass feature assembly entirely.
        effective_middleware = list(middleware)
    else:
        feat = features or RuntimeFeatures()
        effective_middleware, feature_tools = assemble_chain(
            feat,
            middleware_deps or MiddlewareChainConfig(),
            name=name,
            plan_mode=plan_mode,
            extra_middleware=extra_middleware or [],
        )
        # Append feature-injected tools (deduplicating by name
        # so user-provided tools win on collision).
        existing_names = {t.name for t in effective_tools}
        for t in feature_tools:
            if t.name not in existing_names:
                effective_tools.append(t)
                existing_names.add(t.name)

    return _lc_create_agent(
        model=model,
        tools=effective_tools or None,
        middleware=effective_middleware,
        system_prompt=system_prompt,
        state_schema=effective_state,
        checkpointer=checkpointer,
        name=name,
    )



