"""setup_agent tool factory.

Defines or modifies a custom subagent at runtime. The full
behaviour (config.yaml round-trip, validation) is implemented in
stage 5.
"""

from __future__ import annotations

from langchain.tools import BaseTool, tool


def make_setup_agent_tool(tool_name: str = "setup_agent") -> BaseTool:
    """Create a ``setup_agent`` tool with a custom name.

    Args:
        tool_name: The name registered with the LLM. Default
            ``"setup_agent"``.
    """

    @tool(tool_name, parse_docstring=True)
    def setup_agent(name: str, description: str, system_prompt: str) -> str:
        """Register a custom subagent.

        Args:
            name: The role name.
            description: When the parent should delegate to this role.
            system_prompt: The system prompt guiding the subagent.
        """
        return "ok"

    return setup_agent
