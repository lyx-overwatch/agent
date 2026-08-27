"""Tool subsystem for agent runtime.

Exposes the tool-naming factory pattern: each built-in tool is
created via a ``make_*_tool(tool_name=...)`` constructor that
parameterises the tool's registered name.

Why parameterise tool names?
    Tool names are part of the LLM-facing contract — the parent
    agent invokes them by name. Different products may want
    different names (e.g. ``ask_clarification`` vs
    ``clarify_with_user``), and the same product may need to
    rename tools to avoid conflicts. The factory pattern lets
    callers override names without forking the tool
    implementation.

The SDK ships with the factory interfaces and the canonical
DeerFlow names as defaults. A fresh project can use any
factory and pass its own ``tool_name=...`` argument.

The :func:`load_tools` function and :class:`ToolConfig` data
class (in :mod:`agent_sdk.tools.loader`) are the brand-neutral
entry point for assembling a tool list from class-path
configuration, deduplicating, and applying group filters.
"""

from agent_sdk.tools.factory import (
    make_ask_clarification_tool,
    make_present_files_tool,
    make_setup_agent_tool,
    make_task_tool,
    make_view_image_tool,
)
from agent_sdk.tools.loader import LoadResult, ToolConfig, load_tools

__all__ = [
    # factory
    "make_ask_clarification_tool",
    "make_present_files_tool",
    "make_view_image_tool",
    "make_task_tool",
    "make_setup_agent_tool",
    # loader
    "LoadResult",
    "ToolConfig",
    "load_tools",
]
