"""RuntimeFeatures — declarative feature flags for :func:`create_agent`.

The :class:`RuntimeFeatures` dataclass lets a caller express
*which* middlewares the agent runtime should use, without having
to assemble the chain by hand. Every field accepts the same
three-way state:

* ``True`` — use the SDK's built-in default middleware for
  that feature.
* ``False`` — disable the feature (no middleware, no tool).
* An :class:`AgentMiddleware` instance — use *this* middleware
  instead of the built-in default.

Every feature accepts ``True`` (use the SDK's built-in default),
``False`` (disable), or a custom :class:`AgentMiddleware` instance.
Features that require extra configuration (``summarization`` needs a
model, ``skills`` needs a path) will
raise :class:`ValueError` at chain-assembly time if the required
dependency is missing from :class:`MiddlewareChainConfig`.

This mirrors the original ``deerflow.agents.features.RuntimeFeatures``
contract (per ADR-010 the dataclass is re-implemented, not
imported), so the ``DeerFlowAgent`` preset can reuse it with
zero behavioural change.

Example:

    from agent_sdk.runtime import RuntimeFeatures, create_agent

    # Use the built-in defaults for everything that's on by
    # default; opt in to memory and subagent features.
    features = RuntimeFeatures(memory=True, subagent=True)
    agent = create_agent(model=my_model, features=features)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware


@dataclass
class RuntimeFeatures:
    """Declarative feature flags for :func:`create_agent`.

    Attributes:
        sandbox: Sandbox infrastructure middlewares (ThreadData →
            Uploads → Sandbox). Defaults to ``True`` (stage 5.6+)
            to match the original ``create_deerflow_agent``
            contract — callers can opt out with ``sandbox=False``
            if they do not have a :class:`PathProvider` /
            :class:`SandboxProvider` available.
        memory: Long-term memory middleware. Defaults to ``False``
            (the runtime is opt-in for memory).
        summarization: Conversation summarization. No built-in
            default — supply a custom :class:`AgentMiddleware` or
            leave at ``False``.
        subagent: Subagent delegation (``task`` tool + the
            subagent limit middleware). Defaults to ``False``.
        vision: Image-viewing (``view_image`` tool + middleware).
            Defaults to ``False``.
        auto_title: Auto-generate a title for each thread.
            Defaults to ``False``.
        skills: Inject the ``<available_skills>`` block into the
            system prompt. No built-in default — supply a
            custom :class:`AgentMiddleware` or leave at ``False``.
    """

    sandbox: bool | AgentMiddleware = True
    memory: bool | AgentMiddleware = False
    summarization: bool | AgentMiddleware = False
    subagent: bool | AgentMiddleware = False
    vision: bool | AgentMiddleware = False
    auto_title: bool | AgentMiddleware = False
    skills: bool | AgentMiddleware = False

    def is_enabled(self, name: str) -> bool:
        """Return ``True`` if the named feature is on (default or custom)."""
        value = getattr(self, name, False)
        return value is not False
