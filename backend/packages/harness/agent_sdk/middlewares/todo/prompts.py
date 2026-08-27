"""TodoPrompts — the brand-neutral injection point for todo list prompts.

The :class:`TodoPrompts` dataclass bundles the two pieces of
prompt text that :class:`TodoMiddleware` exposes to the LLM:

* ``system_prompt`` — appended to the system message to teach
  the model how to use the ``write_todos`` tool;
* ``tool_description`` — replaces the default tool description
  on the ``write_todos`` tool itself.

Why a dataclass and not two separate parameters?
    * Keeps the constructor of :class:`TodoMiddleware` short;
    * Lets a single preset supply both at once;
    * Mirrors the ``AuditRules`` injection point used in
      :mod:`agent_sdk.sandbox.audit`.

The defaults below are deliberately minimal and project-agnostic.
The DeerFlow preset replaces them with a more opinionated
variant — see
:mod:`agent_sdk.presets.deerflow.prompts.todo`.
"""

from __future__ import annotations

from dataclasses import dataclass

# A minimal, brand-neutral system prompt for the ``write_todos`` tool.
# The wording is intentionally generic — no reference to DeerFlow,
# sub-agents, or any product-specific concept.
DEFAULT_TODO_SYSTEM_PROMPT = """
<todo_list_system>
You have access to the `write_todos` tool to help manage complex multi-step objectives.
Rules:
- Mark todos as completed IMMEDIATELY after finishing each step
- Keep exactly one task as `in_progress` at any time
- Use this for complex tasks (3+ steps); for simple tasks, complete directly
</todo_list_system>
""".strip()

# A minimal, brand-neutral tool description for ``write_todos``.
DEFAULT_TODO_TOOL_DESCRIPTION = (
    "Use this tool to create and manage a structured task list for complex work sessions. "
    "Only use for complex tasks (3+ steps)."
)


@dataclass(frozen=True)
class TodoPrompts:
    """The two pieces of prompt text :class:`TodoMiddleware` exposes.

    Both fields are required; an empty string is allowed (it
    suppresses that injection), but the typical use is to pass
    the ``DEFAULT_*`` constants from this module or the
    DeerFlow preset's richer variants.

    Attributes:
        system_prompt: Appended to the system message slot. Used
            to teach the model when and how to use ``write_todos``.
        tool_description: Replaces the default tool description on
            the ``write_todos`` tool. The LLM sees this when it
            considers whether to call the tool.
    """

    system_prompt: str
    tool_description: str

    @classmethod
    def default(cls) -> TodoPrompts:
        """Return a :class:`TodoPrompts` populated with the brand-neutral defaults."""
        return cls(
            system_prompt=DEFAULT_TODO_SYSTEM_PROMPT,
            tool_description=DEFAULT_TODO_TOOL_DESCRIPTION,
        )
