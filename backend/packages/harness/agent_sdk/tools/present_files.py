"""present_files tool factory.

Makes files visible to the user for viewing and rendering in the
client interface. The full behaviour (path validation, virtual
prefix substitution) is implemented in stage 5.
"""

from __future__ import annotations

from langchain.tools import BaseTool, tool


def make_present_files_tool(tool_name: str = "present_files") -> BaseTool:
    """Create a ``present_files`` tool with a custom name.

    Args:
        tool_name: The name registered with the LLM. Default
            ``"present_files"``.
    """

    @tool(tool_name, parse_docstring=True)
    def present_files(filepaths: list[str]) -> str:
        """Make files visible to the user for viewing and rendering.

        When to use:
        * Making any file available for the user to view, download,
          or interact with.
        * Presenting multiple related files at once.
        * After creating files that should be presented to the user.

        Args:
            filepaths: Absolute virtual paths to files under the
                outputs directory (e.g. ``/agent-data/outputs/...``).

        Returns:
            A status string (placeholder in this stub).
        """
        return "ok"

    return present_files
