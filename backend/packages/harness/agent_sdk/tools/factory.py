"""Tool factory pattern for parameterised tool naming.

Each tool is constructed via a ``make_*_tool(tool_name=...)``
function. The default name matches the canonical DeerFlow name
(``ask_clarification``, ``present_files``, etc.) so that the
DeerFlow preset gets the right LLM-facing contract with no
extra arguments; other projects override via the ``tool_name``
parameter.

This module re-exports the factory functions from
``agent_sdk.tools.*`` so callers can do:

    from agent_sdk.tools import make_present_files_tool
    tool = make_present_files_tool(tool_name="show_files")
"""

from __future__ import annotations

from langchain.tools import BaseTool

from agent_sdk.tools.ask_clarification import make_ask_clarification_tool
from agent_sdk.tools.present_files import make_present_files_tool
from agent_sdk.tools.setup_agent import make_setup_agent_tool
from agent_sdk.tools.task import make_task_tool
from agent_sdk.tools.view_image import make_view_image_tool

__all__ = [
    "make_ask_clarification_tool",
    "make_present_files_tool",
    "make_view_image_tool",
    "make_task_tool",
    "make_setup_agent_tool",
    "BaseTool",
]
