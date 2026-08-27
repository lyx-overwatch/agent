"""DeerFlowAgent — the DeerFlow preset convenience class.

This module is the re-implementation (per ADR-010) of the
DeerFlow agent assembly logic. It wraps
:func:`agent_sdk.runtime.create_agent` with DeerFlow-specific
defaults so a caller gets a fully-configured agent in a few
lines of code.

Usage::

    from agent_sdk.presets.deerflow import DeerFlowAgent

    agent = DeerFlowAgent(model=my_model)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "Hello"}]})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_sdk.presets.deerflow.audit import DeerFlowAuditRules
from agent_sdk.presets.deerflow.memory import DeerFlowMemorySchema
from agent_sdk.presets.deerflow.paths import DeerFlowPathProvider
from agent_sdk.presets.deerflow.prompts.system import (
    DEFAULT_AGENT_NAME,
    apply_prompt_template,
)
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph


# ------------------------------------------------------------------
# DeerFlow default features
# ------------------------------------------------------------------

#: The default feature set for a DeerFlow agent.
#: Mirrors the backend ``make_lead_agent`` defaults.
DEERFLOW_DEFAULT_FEATURES = RuntimeFeatures(
    sandbox=True,
    memory=False,
    summarization=False,
    subagent=True,
    vision=True,
    auto_title=True,
    skills=True,
)


# ------------------------------------------------------------------
# DeerFlowAgent
# ------------------------------------------------------------------


@dataclass
class DeerFlowAgent:
    """Convenience class that assembles a DeerFlow agent.

    This class bundles the DeerFlow presets — path provider,
    memory schema, subagent registry, audit rules, system
    prompt — and passes them to
    :func:`agent_sdk.runtime.create_agent`.

    Args:
        model: A LangChain chat model instance (**required**).
        tools: Optional list of user-provided tools.
        features: Override the default feature flags. When
            ``None``, :data:`DEERFLOW_DEFAULT_FEATURES` is used
            (sandbox + subagent + vision + auto_title + skills).
        system_prompt: Override the system prompt. When
            ``None``, the DeerFlow system prompt is generated
            via :func:`apply_prompt_template`.
        middleware: Full-takeover middleware list. Cannot be
            combined with *features*.
        extra_middleware: Additional middlewares inserted into
            the auto-assembled chain.
        path_provider: Override the path provider. Defaults to
            :class:`DeerFlowPathProvider`.
        memory_schema_cls: Override the memory schema. Defaults
            to :class:`DeerFlowMemorySchema`.
        agent_name: Display name for the agent (default
            ``"DeerFlow 2.0"``). Used in the system prompt and
            forwarded to middlewares that care.
        plan_mode: Enable task-list tracking.
        state_schema: Custom LangGraph state type.
        checkpointer: Optional persistence backend.
        **l2_overrides: Additional keyword arguments are merged
            into the :class:`MiddlewareChainConfig`. Useful for
            injecting a ``sandbox_provider``,
            ``summarization_model``, ``memory_storage``, etc.

    Example::

        agent = DeerFlowAgent(
            model=my_model,
            tools=[my_tool],
            agent_name="MyAssistant",
            plan_mode=True,
        )
        # Access the compiled graph:
        graph = agent.graph
    """

    model: BaseChatModel

    # User-tunable
    tools: list[BaseTool] | None = None
    features: RuntimeFeatures | None = None
    system_prompt: str | None = None
    middleware: list[AgentMiddleware] | None = None
    extra_middleware: list[AgentMiddleware] | None = None
    path_provider: Any = field(default_factory=DeerFlowPathProvider)
    memory_schema_cls: type = DeerFlowMemorySchema
    agent_name: str = DEFAULT_AGENT_NAME
    plan_mode: bool = False
    state_schema: type | None = None
    checkpointer: Any = None

    # Extra overrides for MiddlewareChainConfig
    sandbox_provider: Any = None
    audit_rules: Any = field(default_factory=DeerFlowAuditRules)
    title_model_factory: Any = None
    title_prompts: Any = None
    summarization_model: Any = None
    summarization_hooks: Any = None
    summarization_partitioner: Any = None
    memory_storage: Any = None
    todo_prompts: Any = None
    skills_path: Any = None

    # Mutable fields (set by __post_init__)
    _graph: CompiledStateGraph | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._graph = None

    # -- graph -----------------------------------------------------------

    @property
    def graph(self) -> CompiledStateGraph:
        """The compiled LangGraph agent.

        Built lazily on first access. Subsequent accesses
        return the cached graph.
        """
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    def _build(self) -> CompiledStateGraph:
        from agent_sdk.runtime.entry import create_agent

        # --- System prompt ---
        prompt = self.system_prompt
        if prompt is None:
            prompt = apply_prompt_template(
                agent_name=self.agent_name,
                subagent_enabled=self._feat("subagent"),
                max_concurrent_subagents=3,
                bash_available=False,
            )

        # --- MiddlewareChainConfig ---
        mw_deps = MiddlewareChainConfig(
            path_provider=self.path_provider,
            sandbox_provider=self.sandbox_provider,
            audit_rules=self.audit_rules,
            title_model_factory=self.title_model_factory,
            title_prompts=self.title_prompts,
            summarization_model=self.summarization_model,
            summarization_hooks=self.summarization_hooks,
            summarization_partitioner=self.summarization_partitioner,
            memory_schema_cls=self.memory_schema_cls,
            memory_storage=self.memory_storage,
            todo_prompts=self.todo_prompts,
            skills_path=self.skills_path,
        )

        # --- Features ---
        features = self.features if self.features is not None else DEERFLOW_DEFAULT_FEATURES

        # --- Build ---
        return create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
            middleware=self.middleware,
            features=features,
            extra_middleware=self.extra_middleware,
            state_schema=self.state_schema,
            checkpointer=self.checkpointer,
            name=self.agent_name,
            middleware_deps=mw_deps,
            plan_mode=self.plan_mode,
        )

    # -- helpers ----------------------------------------------------------

    def _feat(self, name: str) -> bool:
        """Return whether the named feature is enabled."""
        features = self.features if self.features is not None else DEERFLOW_DEFAULT_FEATURES
        value = getattr(features, name, False)
        return value is not False

    # -- convenience methods -----------------------------------------------

    async def ainvoke(self, input_data: dict, config: dict | None = None) -> dict:
        """Invoke the agent asynchronously.

        Args:
            input_data: The LangGraph state dict (must include
                ``messages``).
            config: Optional LangGraph run config (thread_id, etc.).
        """
        return await self.graph.ainvoke(input_data, config=config)

    def invoke(self, input_data: dict, config: dict | None = None) -> dict:
        """Invoke the agent synchronously.

        Args:
            input_data: The LangGraph state dict (must include
                ``messages``).
            config: Optional LangGraph run config (thread_id, etc.).
        """
        result: dict = self.graph.invoke(input_data, config=config)
        return result

    async def astream(self, input_data: dict, config: dict | None = None):
        """Stream events from the agent asynchronously."""
        async for event in self.graph.astream(input_data, config=config):
            yield event

    def stream(self, input_data: dict, config: dict | None = None):
        """Stream events from the agent synchronously."""
        yield from self.graph.stream(input_data, config=config)


# ------------------------------------------------------------------
# Public surface
# ------------------------------------------------------------------

__all__ = [
    "DEERFLOW_DEFAULT_FEATURES",
    "DeerFlowAgent",
]
