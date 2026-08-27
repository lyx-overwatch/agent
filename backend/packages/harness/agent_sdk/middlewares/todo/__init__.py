"""TodoMiddleware and its prompt injection point.

The :class:`TodoPrompts` dataclass is the brand-neutral injection
point for the system prompt and tool description that
:class:`TodoMiddleware` exposes to the LLM. The default values
(:data:`DEFAULT_TODO_SYSTEM_PROMPT`, :data:`DEFAULT_TODO_TOOL_DESCRIPTION`)
are deliberately minimal and product-agnostic. The DeerFlow preset
supplies a richer variant in
:mod:`agent_sdk.presets.deerflow.prompts.todo`.
"""

from __future__ import annotations

from agent_sdk.middlewares.todo.middleware import TodoMiddleware
from agent_sdk.middlewares.todo.prompts import (
    DEFAULT_TODO_SYSTEM_PROMPT,
    DEFAULT_TODO_TOOL_DESCRIPTION,
    TodoPrompts,
)

__all__ = [
    "TodoPrompts",
    "DEFAULT_TODO_SYSTEM_PROMPT",
    "DEFAULT_TODO_TOOL_DESCRIPTION",
    "TodoMiddleware",
]
