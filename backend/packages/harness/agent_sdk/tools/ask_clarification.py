"""ask_clarification tool factory.

Asks the user a clarifying question when the task is ambiguous.

The factory pattern lets callers override the LLM-facing tool name
(default ``"ask_clarification"``):

    tool = make_ask_clarification_tool(tool_name="clarify")

The tool surface mirrors the backend's
``deerflow.tools.builtins.clarification_tool.ask_clarification_tool``:
- ``return_direct=True`` — the framework short-circuits further
  reasoning after the tool returns so the LLM does not try to
  rephrase the question.
- ``clarification_type`` is a required ``Literal`` matching the
  backend's five categories (``missing_info`` /
  ``ambiguous_requirement`` / ``approach_choice`` /
  ``risk_confirmation`` / ``suggestion``).
- The body is still a placeholder — the real interruption is
  done by :class:`agent_sdk.middlewares.clarification.ClarificationMiddleware`,
  which intercepts the tool call. This module only ships the
  tool schema the LLM binds to.
"""

from __future__ import annotations

from typing import Literal

from langchain.tools import BaseTool, tool


def make_ask_clarification_tool(tool_name: str = "ask_clarification") -> BaseTool:
    """Create an ``ask_clarification`` tool with a custom name.

    Args:
        tool_name: The name registered with the LLM. Default
            ``"ask_clarification"`` (the canonical DeerFlow name).

    Returns:
        A LangChain ``BaseTool`` ready to be passed to ``create_agent``.
    """

    @tool(tool_name, parse_docstring=True, return_direct=True)
    def ask_clarification(
        question: str,
        clarification_type: Literal[
            "missing_info",
            "ambiguous_requirement",
            "approach_choice",
            "risk_confirmation",
            "suggestion",
        ],
        context: str | None = None,
        options: list[str] | None = None,
    ) -> str:
        """Ask the user for clarification when you need more information to proceed.

        Use this tool when you encounter situations where you cannot proceed without user input:

        - **Missing information**: Required details not provided (e.g., file paths, URLs, specific requirements)
        - **Ambiguous requirements**: Multiple valid interpretations exist
        - **Approach choices**: Several valid approaches exist and you need user preference
        - **Risky operations**: Destructive actions that need explicit confirmation (e.g., deleting files, modifying production)
        - **Suggestions**: You have a recommendation but want user approval before proceeding

        The execution will be interrupted and the question will be presented to the user.
        Wait for the user's response before continuing.

        When to use ask_clarification:
        - You need information that wasn't provided in the user's request
        - The requirement can be interpreted in multiple ways
        - Multiple valid implementation approaches exist
        - You're about to perform a potentially dangerous operation
        - You have a recommendation but need user approval

        Best practices:
        - Ask ONE clarification at a time for clarity
        - Be specific and clear in your question
        - Don't make assumptions when clarification is needed
        - For risky operations, ALWAYS ask for confirmation
        - After calling this tool, execution will be interrupted automatically

        Args:
            question: The clarification question to ask the user. Be specific and clear.
            clarification_type: The type of clarification needed (missing_info, ambiguous_requirement, approach_choice, risk_confirmation, suggestion).
            context: Optional context explaining why clarification is needed. Helps the user understand the situation.
            options: Optional list of choices (for approach_choice or suggestion types). Present clear options for the user to choose from.
        """
        # The actual logic is handled by ClarificationMiddleware which intercepts this
        # tool call and interrupts execution to present the question to the user.
        return "Clarification request processed by middleware"

    return ask_clarification
