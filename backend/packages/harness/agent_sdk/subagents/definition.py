"""Subagent definition data class.

This is a re-implementation (per ADR-010) of
``backend.subagents.config.SubagentConfig``. The shape is
intentionally similar so that the DeerFlow preset can map the
backend's role definitions to this class with minimal translation
cost. Generic projects can use this class directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubagentDefinition:
    """Configuration for a subagent role.

    Attributes:
        name: Unique identifier for the subagent.
        description: When the parent agent should delegate to this
            subagent. Surfaced in the parent's tool description.
        system_prompt: The system prompt that guides the subagent's
            behavior.
        tools: Optional list of tool names to allow. If ``None``,
            inherits all tools from the parent.
        disallowed_tools: Optional list of tool names to deny. By
            default the ``task`` tool is denied to prevent unbounded
            nesting.
        skills: Optional list of skill names to load. If ``None``,
            inherits all enabled skills. If an empty list, no skills
            are loaded.
        model: Model to use. ``"inherit"`` uses parent's model.
        max_turns: Maximum number of agent turns before stopping.
        timeout_seconds: Maximum execution time in seconds. Default
            900 (15 minutes).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    skills: list[str] | None = None
    model: str = "inherit"
    max_turns: int = 50
    timeout_seconds: int = 900
