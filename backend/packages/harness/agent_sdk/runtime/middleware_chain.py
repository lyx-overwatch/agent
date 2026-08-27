"""Middleware chain assembly for the SDK runtime.

This module is the brand-neutral re-implementation (per
ADR-010) of the chain-assembly logic in
``deerflow.agents.factory._assemble_from_features``.  It
takes a :class:`agent_sdk.runtime.RuntimeFeatures` flag
declaration and a :class:`MiddlewareChainConfig` (which
holds the runtime dependencies the feature middlewares need) and
produces an ordered list of middlewares + a list of extra
tools to register with the agent.

The order is **the SDK's public contract** — the unit
tests in ``tests/runtime/test_middleware_chain.py`` pin
the exact sequence so any change shows up in CI.

Built-in chain (when every feature is enabled)::

    0.  ThreadDataMiddleware            (sandbox)
    1.  UploadsMiddleware                (sandbox)
    2.  SandboxMiddleware                (sandbox)
    3.  DanglingToolCallMiddleware       (always)
    4.  LLMErrorHandlingMiddleware       (always)
    5.  SandboxAuditMiddleware           (sandbox)
    6.  ToolErrorHandlingMiddleware      (always)
    7.  SummarizationMiddleware          (summarization)
    8.  TodoMiddleware                   (plan_mode)
    9.  TokenUsageMiddleware            (always)
    10. TitleMiddleware                  (auto_title)
    11. MemoryMiddleware                 (memory)
    12. ViewImageMiddleware              (vision)
    13. DeferredToolFilterMiddleware     (always)
    14. SubagentLimitMiddleware          (subagent)
    15. LoopDetectionMiddleware          (always)
    16. StateSizeMonitorMiddleware       (always)
    17. ClarificationMiddleware          (always last)

``ClarificationMiddleware`` is **always last** among the
built-ins: extra middlewares are inserted *before* it
(their default position), and any insertion that would
push it off the tail is re-anchored.

Two-phase ordering:
    1. Built-in chain — fixed sequential append.
    2. Extra middlewares — inserted via ``@Next`` /
       ``@Prev`` (see :func:`_insert_extra_middlewares`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from agent_sdk.middlewares.summarization import BeforeSummarizationHook
    from agent_sdk.middlewares.title import TitlePrompts
    from agent_sdk.middlewares.todo.prompts import TodoPrompts
    from agent_sdk.paths.provider import PathProvider
    from agent_sdk.sandbox.audit.rules import AuditRules
    from agent_sdk.sandbox.base import SandboxProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration data class
# ---------------------------------------------------------------------------


@dataclass
class MiddlewareChainConfig:
    """Bundle of runtime dependencies the feature middlewares need.

    Every feature that the user enables in
    :class:`agent_sdk.runtime.RuntimeFeatures` requires
    some runtime dependency (a :class:`PathProvider`, a
    chat model, a memory storage backend, …).  This data
    class is the single injection point that carries them
    all.

    Attributes:
        path_provider: Required for ``sandbox=True``
            (drives :class:`ThreadDataMiddleware`,
            :class:`UploadsMiddleware`).
        sandbox_provider: Required for ``sandbox=True``
            (drives :class:`SandboxMiddleware`).
        audit_rules: Required for ``sandbox=True`` (drives
            :class:`SandboxAuditMiddleware`); when omitted
            the no-op :class:`DefaultAuditRules` is used.
        title_model_factory: Optional async-callable that
            returns a chat model for
            :class:`TitleMiddleware`; when omitted the
            middleware uses a local fallback.
        title_prompts: Optional :class:`TitlePrompts`;
            when omitted the brand-neutral default is used.
        summarization_model: Required for
            ``summarization=True`` (drives
            :class:`SummarizationMiddleware`).
        summarization_hooks: Optional list of
            :class:`BeforeSummarizationHook` callbacks.
        summarization_partitioner: Optional
            :data:`MessagePartitioner` that controls how the
            message list is split before summarisation. When
            omitted the brand-neutral :func:`default_partitioner`
            is used (no skill rescue). Products that want
            skill-rescue can pass
            :func:`agent_sdk.middlewares.summarization.skill_rescue_partitioner`
            with their own skill-tool name set.
        memory_schema_cls: Required for ``memory=True``
            (drives :class:`MemoryMiddleware`).
        memory_storage: Required for ``memory=True``
            (drives :class:`MemoryMiddleware`).
        todo_prompts: Optional :class:`TodoPrompts` for
            :class:`TodoMiddleware`; when omitted the
            brand-neutral default is used.
        skills_path: Optional path to a skills root directory
            (containing public and custom sub-dirs); when set,
            the chain includes :class:`SkillsMiddleware`
            (the prompt section is only added if enabled
            skills exist).
    """

    path_provider: PathProvider | None = None
    sandbox_provider: SandboxProvider | None = None
    audit_rules: AuditRules | None = None
    title_model_factory: Callable[[], Any] | None = None
    title_prompts: TitlePrompts | None = None
    summarization_model: BaseChatModel | None = None
    summarization_hooks: list[BeforeSummarizationHook] | None = None
    summarization_partitioner: Callable[[list, int], tuple[list, list]] | None = None
    memory_schema_cls: type | None = None
    memory_storage: Any = None
    todo_prompts: TodoPrompts | None = None
    skills_path: Any = None  # pathlib.Path — kept as Any to avoid top-level import cost
    subagent_registry: Any = None  # SubagentRegistry — kept as Any to avoid top-level import cost
    run_subagent: Any = None  # RunSubagent — kept as Any to avoid top-level import cost
    summarization_max_tokens: int | None = None  # trigger_tokens from config.yaml
    summarization_keep_messages: int | None = None  # keep_messages from config.yaml


# ---------------------------------------------------------------------------
# Chain assembly
# ---------------------------------------------------------------------------


def assemble_chain(
    features: Any,
    config: MiddlewareChainConfig,
    *,
    name: str = "default",
    plan_mode: bool = False,
    extra_middleware: list[AgentMiddleware] | None = None,
) -> tuple[list[AgentMiddleware], list[BaseTool]]:
    """Build the ordered middleware chain + extra tools from *features*.

    Args:
        features: A :class:`agent_sdk.runtime.RuntimeFeatures`
            (or any object with the same attribute set).
        config: Runtime dependencies (paths, sandbox, memory,
            …) the feature middlewares need.
        name: Agent name — forwarded to middlewares that
            care (e.g. :class:`MemoryMiddleware`).
        plan_mode: When ``True``, enable the always-on
            :class:`TodoMiddleware` regardless of any
            feature flag.
        extra_middleware: Optional user middlewares; each
            is inserted via ``@Next`` / ``@Prev`` anchors.
            Unanchored items are inserted *before*
            :class:`ClarificationMiddleware`.

    Returns:
        ``(middlewares, extra_tools)`` ready to be passed
        to :func:`langchain.agents.create_agent`.

    Raises:
        ValueError: If a feature is enabled but the
            corresponding config field is missing.
    """
    chain: list[AgentMiddleware] = []
    extra_tools: list[BaseTool] = []

    # --- [0-2] Sandbox infrastructure -------------------------------------
    if features.sandbox is not False:
        _build_sandbox_infrastructure(features, config, chain, extra_tools)

    # --- [3] DanglingToolCall (always) ------------------------------------
    from agent_sdk.middlewares.dangling_tool_call import DanglingToolCallMiddleware

    chain.append(DanglingToolCallMiddleware())

    # --- [4] LLMErrorHandling (always) ------------------------------------
    from agent_sdk.middlewares.llm_error import LLMErrorHandlingMiddleware

    chain.append(LLMErrorHandlingMiddleware())

    # --- [5] SandboxAudit (always when sandbox is on) --------------------
    if features.sandbox is not False:
        from agent_sdk.sandbox.audit import SandboxAuditMiddleware

        chain.append(SandboxAuditMiddleware(audit_rules=config.audit_rules))

    # --- [6] ToolErrorHandling (always) -----------------------------------
    from agent_sdk.middlewares.tool_error_handling import ToolErrorHandlingMiddleware

    chain.append(ToolErrorHandlingMiddleware())

    # --- [7] Summarization (optional) -------------------------------------
    if features.summarization is not False:
        _build_summarization(features, config, chain)

    # --- [8] TodoMiddleware (plan_mode) -----------------------------------
    if plan_mode:
        _build_todo(config, chain)

    # --- [9] TokenUsage (always) -------------------------------------------
    from agent_sdk.middlewares.token_usage import TokenUsageMiddleware

    chain.append(TokenUsageMiddleware())

    # --- [10] Title (optional) ---------------------------------------------
    if features.auto_title is not False:
        _build_title(features, config, chain)

    # --- [11] Memory (optional) -------------------------------------------
    if features.memory is not False:
        _build_memory(features, config, chain, name=name)

    # --- [11.5] Skills (optional) -----------------------------------------
    if features.skills is not False:
        _build_skills(features, config, chain)

    # --- [12] ViewImage (optional) ----------------------------------------
    if features.vision is not False:
        _build_vision(chain, extra_tools)

    # --- [13] DeferredToolFilter (always) ---------------------------------
    from agent_sdk.middlewares.deferred_tool_filter import DeferredToolFilterMiddleware

    chain.append(DeferredToolFilterMiddleware())

    # --- [14] SubagentLimit (optional) ------------------------------------
    if features.subagent is not False:
        _build_subagent(chain, extra_tools, config)

    # --- [15] LoopDetection (always) --------------------------------------
    from agent_sdk.middlewares.loop_detection import LoopDetectionMiddleware

    chain.append(LoopDetectionMiddleware())

    # --- [15.5] StateSizeMonitor (always) ---------------------------------
    from agent_sdk.middlewares.state_size_monitor import StateSizeMonitorMiddleware

    chain.append(StateSizeMonitorMiddleware())

    # --- [15.6] ModelCallCapture (always) -----------------------------------
    # Must be placed after all message-modifying middlewares so it
    # captures the messages array as it is actually sent to the model
    # (after summarization, dangling-tool-call patches, etc.).
    from agent_sdk.middlewares.model_call_capture import ModelCallCaptureMiddleware

    chain.append(ModelCallCaptureMiddleware())

    # --- [16] Clarification (always last among built-ins) ---------------
    from agent_sdk.middlewares.clarification import (
        DEFAULT_CLARIFICATION_TOOL_NAME,
        ClarificationMiddleware,
    )
    from agent_sdk.tools.ask_clarification import make_ask_clarification_tool

    chain.append(ClarificationMiddleware())
    extra_tools.append(make_ask_clarification_tool(tool_name=DEFAULT_CLARIFICATION_TOOL_NAME))

    # --- Insert extra middlewares via @Next / @Prev ----------------------
    if extra_middleware:
        _insert_extra_middlewares(chain, list(extra_middleware))
        # Invariant: ClarificationMiddleware must always be the
        # last built-in.  An @Next(ClarificationMiddleware) could
        # have pushed it off the tail; restore the invariant.
        from agent_sdk.middlewares.clarification import ClarificationMiddleware as _Clar

        clar_idx = next((i for i, m in enumerate(chain) if isinstance(m, _Clar)), None)
        if clar_idx is not None and clar_idx != len(chain) - 1:
            chain.append(chain.pop(clar_idx))

    return chain, extra_tools


# ---------------------------------------------------------------------------
# Per-feature builders (helpers, not exported)
# ---------------------------------------------------------------------------


def _build_sandbox_infrastructure(
    features: Any,
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
    extra_tools: list[BaseTool],
) -> None:
    """Append ThreadData / Uploads / Sandbox middlewares."""
    if config.path_provider is None:
        raise ValueError(
            "RuntimeFeatures.sandbox=True requires MiddlewareChainConfig.path_provider. "
            "Construct a PathProvider (e.g. DeerFlowPathProvider) and pass it via middleware_deps."
        )
    if config.sandbox_provider is None:
        raise ValueError(
            "RuntimeFeatures.sandbox=True requires MiddlewareChainConfig.sandbox_provider. "
            "Construct a SandboxProvider and pass it via middleware_deps."
        )

    from agent_sdk.middlewares.thread_data import ThreadDataMiddleware
    from agent_sdk.middlewares.uploads import UploadsMiddleware
    from agent_sdk.sandbox.middleware import SandboxMiddleware

    if isinstance(features.sandbox, list):
        # Caller supplied a fully-built list — use it directly.
        for mw in features.sandbox:
            chain.append(mw)
        return

    chain.append(ThreadDataMiddleware(path_provider=config.path_provider, lazy_init=True))
    chain.append(UploadsMiddleware(path_provider=config.path_provider))
    chain.append(SandboxMiddleware(provider=config.sandbox_provider, lazy_init=True))


def _build_skills(
    features: Any,
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
) -> None:
    """Append a skills-prompt-injection middleware.

    Two ways to enable:

    * ``features.skills`` is an :class:`AgentMiddleware`
      instance — use it as-is.
    * ``features.skills`` is ``True`` and ``config.skills_path``
      is a path — wire :class:`SkillsMiddleware`.
    """
    from langchain.agents.middleware import AgentMiddleware

    from agent_sdk.skills import SkillsMiddleware

    if isinstance(features.skills, AgentMiddleware):
        chain.append(features.skills)
        return
    if config.skills_path is None:
        raise ValueError(
            "RuntimeFeatures.skills=True requires MiddlewareChainConfig.skills_path "
            "(path to a skills root directory)."
        )
    chain.append(
        SkillsMiddleware(
            skills_path=config.skills_path,
        )
    )


def _build_summarization(
    features: Any,
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
) -> None:
    """Append a summarization middleware."""
    from langchain.agents.middleware import AgentMiddleware

    if isinstance(features.summarization, AgentMiddleware):
        chain.append(features.summarization)
        return
    if config.summarization_model is None:
        raise ValueError(
            "RuntimeFeatures.summarization=True requires "
            "MiddlewareChainConfig.summarization_model (SummarizationMiddleware needs a chat model)."
        )
    from agent_sdk.middlewares.summarization import (
        MessagePartitioner,
        SummarizationMiddleware,
        default_partitioner,
    )

    partitioner: MessagePartitioner = config.summarization_partitioner or default_partitioner

    # Read thresholds from config, falling back to the middleware's own defaults.
    _max_tokens = config.summarization_max_tokens if config.summarization_max_tokens is not None else 4000
    _keep_msgs = config.summarization_keep_messages if config.summarization_keep_messages is not None else 20

    chain.append(
        SummarizationMiddleware(
            model=config.summarization_model,
            hooks=config.summarization_hooks,
            message_partitioner=partitioner,
            max_tokens_before_summary=_max_tokens,
            messages_to_keep=_keep_msgs,
        )
    )


def _build_todo(
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
) -> None:
    """Append a todo middleware using the configured prompts (or default)."""
    from agent_sdk.middlewares.todo.middleware import TodoMiddleware

    if config.todo_prompts is not None:
        chain.append(TodoMiddleware(prompts=config.todo_prompts))
    else:
        chain.append(TodoMiddleware(prompts=None))


def _build_title(
    features: Any,
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
) -> None:
    """Append a title middleware."""
    from langchain.agents.middleware import AgentMiddleware

    if isinstance(features.auto_title, AgentMiddleware):
        chain.append(features.auto_title)
        return
    from agent_sdk.middlewares.title import TitleMiddleware

    chain.append(
        TitleMiddleware(
            model_factory=config.title_model_factory,
            prompts=config.title_prompts,
        )
    )


def _build_memory(
    features: Any,
    config: MiddlewareChainConfig,
    chain: list[AgentMiddleware],
    *,
    name: str,
) -> None:
    """Append a memory middleware."""
    from langchain.agents.middleware import AgentMiddleware

    if isinstance(features.memory, AgentMiddleware):
        chain.append(features.memory)
        return
    if config.memory_schema_cls is None or config.memory_storage is None:
        raise ValueError(
            "RuntimeFeatures.memory=True requires MiddlewareChainConfig.memory_schema_cls "
            "and memory_storage."
        )
    from agent_sdk.memory.middleware import MemoryMiddleware

    chain.append(
        MemoryMiddleware(
            memory_schema_cls=config.memory_schema_cls,
            storage=config.memory_storage,
        )
    )


def _build_vision(
    chain: list[AgentMiddleware],
    extra_tools: list[BaseTool],
) -> None:
    """Append the view-image middleware + tool."""
    from agent_sdk.middlewares.view_image import ViewImageMiddleware
    from agent_sdk.tools.view_image import make_view_image_tool

    chain.append(ViewImageMiddleware())
    extra_tools.append(make_view_image_tool())


def _build_subagent(
    chain: list[AgentMiddleware],
    extra_tools: list[BaseTool],
    config: MiddlewareChainConfig,
) -> None:
    """Append the subagent-limit middleware + the ``task`` tool."""
    from agent_sdk.middlewares.subagent_limit import SubagentLimitMiddleware
    from agent_sdk.tools.task import make_task_tool

    chain.append(SubagentLimitMiddleware())
    extra_tools.append(make_task_tool(
        registry=config.subagent_registry,
        run_subagent=config.run_subagent,
    ))


# ---------------------------------------------------------------------------
# Extra-middleware insertion (anchored + unanchored)
# ---------------------------------------------------------------------------


def _insert_extra_middlewares(
    chain: list[AgentMiddleware],
    extras: list[AgentMiddleware],
) -> None:
    """Insert *extras* into *chain* using ``@Next`` / ``@Prev`` anchors.

    The algorithm mirrors the in-tree reference:

    1. Validate: no middleware has both ``@Next`` and ``@Prev``.
    2. Conflict detection: two extras targeting the same anchor
       in the same direction → error; cross-direction targeting
       the same anchor → error.
    3. Unanchored extras are inserted **before**
       :class:`ClarificationMiddleware` (the always-last slot).
    4. Anchored extras are inserted iteratively (supports
       cross-external anchoring); circular dependencies raise
       :class:`ValueError`.
    """

    next_targets: dict[type, type] = {}
    prev_targets: dict[type, type] = {}

    anchored: list[tuple[AgentMiddleware, str, type]] = []
    unanchored: list[AgentMiddleware] = []

    for mw in extras:
        next_anchor = getattr(type(mw), "_next_anchor", None)
        prev_anchor = getattr(type(mw), "_prev_anchor", None)

        if next_anchor and prev_anchor:
            raise ValueError(f"{type(mw).__name__} cannot have both @Next and @Prev")

        if next_anchor:
            if next_anchor in next_targets:
                raise ValueError(
                    f"Conflict: {type(mw).__name__} and {next_targets[next_anchor].__name__} "
                    f"both @Next({next_anchor.__name__})"
                )
            if next_anchor in prev_targets:
                raise ValueError(
                    f"Conflict: {type(mw).__name__} @Next({next_anchor.__name__}) and "
                    f"{prev_targets[next_anchor].__name__} @Prev({next_anchor.__name__}) — "
                    "use cross-anchoring between extras instead"
                )
            next_targets[next_anchor] = type(mw)
            anchored.append((mw, "next", next_anchor))
        elif prev_anchor:
            if prev_anchor in prev_targets:
                raise ValueError(
                    f"Conflict: {type(mw).__name__} and {prev_targets[prev_anchor].__name__} "
                    f"both @Prev({prev_anchor.__name__})"
                )
            if prev_anchor in next_targets:
                raise ValueError(
                    f"Conflict: {type(mw).__name__} @Prev({prev_anchor.__name__}) and "
                    f"{next_targets[prev_anchor].__name__} @Next({prev_anchor.__name__}) — "
                    "use cross-anchoring between extras instead"
                )
            prev_targets[prev_anchor] = type(mw)
            anchored.append((mw, "prev", prev_anchor))
        else:
            unanchored.append(mw)

    # Unanchored → before ClarificationMiddleware (the always-last slot).
    from agent_sdk.middlewares.clarification import ClarificationMiddleware

    clarification_idx = next(
        (i for i, m in enumerate(chain) if isinstance(m, ClarificationMiddleware)),
        len(chain),  # if no Clarification is in the chain, append at the end
    )
    for mw in unanchored:
        chain.insert(clarification_idx, mw)
        clarification_idx += 1

    # Anchored → iterative insertion (supports external-to-external anchoring).
    pending = list(anchored)
    max_rounds = len(pending) + 1
    for _ in range(max_rounds):
        if not pending:
            break
        remaining: list[tuple[AgentMiddleware, str, type]] = []
        for mw, direction, anchor in pending:
            idx = next(
                (i for i, m in enumerate(chain) if isinstance(m, anchor)),
                None,
            )
            if idx is None:
                remaining.append((mw, direction, anchor))
                continue
            if direction == "next":
                chain.insert(idx + 1, mw)
            else:
                chain.insert(idx, mw)
        if len(remaining) == len(pending):
            names = [type(m).__name__ for m, _, _ in remaining]
            anchor_types = {a for _, _, a in remaining}
            remaining_types = {type(m) for m, _, _ in remaining}
            circular = anchor_types & remaining_types
            if circular:
                raise ValueError(
                    f"Circular dependency among extra middlewares: {', '.join(t.__name__ for t in circular)}"
                )
            raise ValueError(
                f"Cannot resolve positions for {', '.join(names)} — "
                f"anchors {', '.join(a.__name__ for _, _, a in remaining)} not found in chain"
            )
        pending = remaining


__all__ = [
    "MiddlewareChainConfig",
    "assemble_chain",
]
