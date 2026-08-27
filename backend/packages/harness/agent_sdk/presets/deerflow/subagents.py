"""DeerFlow preset: SubagentRegistry with general-purpose and bash roles.

:class:`DeerFlowSubagentRegistry` pre-populates two built-in
subagent roles, mirroring the original
``backend.subagents.builtins.BUILTIN_SUBAGENTS``:

* ``general-purpose`` — a capable agent for complex, multi-step
  tasks
* ``bash`` — a command execution specialist for terminal work

The role descriptions and system prompts are re-entered from
scratch here (per ADR-010) — they are **not** imported from
``backend.*``. Behavior is verified by golden fixtures in
``tests/fixtures/subagents/``.

The prompt text is the original DeerFlow prompt verbatim; it
references ``/mnt/user-data/...`` paths, which the SDK's
:class:`DeerFlowPathProvider` virtualises transparently.
"""

from __future__ import annotations

from agent_sdk.subagents.definition import SubagentDefinition

GENERAL_PURPOSE_SYSTEM_PROMPT = """You are a general-purpose subagent working on a delegated task. Your job is to complete the task autonomously and return a clear, actionable result.

<guidelines>
- Focus on completing the delegated task efficiently
- Use available tools as needed to accomplish the goal
- Think step by step but act decisively
- If you encounter issues, explain them clearly in your response
- Return a concise summary of what you accomplished
- Do NOT ask for clarification - work with the information provided
</guidelines>

<output_format>
When you complete the task, provide:
1. A brief summary of what was accomplished
2. Key findings or results
3. Any relevant file paths, data, or artifacts created
4. Issues encountered (if any)
5. Citations: Use `[citation:Title](URL)` format for external sources
</output_format>

<working_directory>
You have access to the same sandbox environment as the parent agent:
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
- Deployment-configured custom mounts may also be available at other absolute container paths; use them directly when the task references those mounted directories
- Treat `/mnt/user-data/workspace` as the default working directory for coding and file IO
- Prefer relative paths from the workspace, such as `hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`, when writing scripts or shell commands
</working_directory>
"""

GENERAL_PURPOSE_DESCRIPTION = """A capable agent for complex, multi-step tasks that require both exploration and action.

Use this subagent when:
- The task requires both exploration and modification
- Complex reasoning is needed to interpret results
- Multiple dependent steps must be executed
- The task would benefit from isolated context management

Do NOT use for simple, single-step operations."""

BASH_AGENT_SYSTEM_PROMPT = """You are a bash command execution specialist. Execute the requested commands carefully and report results clearly.

<guidelines>
- Execute commands one at a time when they depend on each other
- Use parallel execution when commands are independent
- Report both stdout and stderr when relevant
- Handle errors gracefully and explain what went wrong
- Use workspace-relative paths for files under the default workspace, uploads, and outputs directories
- Use absolute paths only when the task references deployment-configured custom mounts outside the default workspace layout
- Be cautious with destructive operations (rm, overwrite, etc.)
</guidelines>

<output_format>
For each command or group of commands:
1. What was executed
2. The result (success/failure)
3. Relevant output (summarized if verbose)
4. Any errors or warnings
</output_format>

<working_directory>
You have access to the sandbox environment:
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
- Deployment-configured custom mounts may also be available at other absolute container paths; use them directly when the task references those mounted directories
- Treat `/mnt/user-data/workspace` as the default working directory for file IO
- Prefer relative paths from the workspace, such as `hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`, when composing commands or helper scripts
</working_directory>
"""

BASH_AGENT_DESCRIPTION = """Command execution specialist for running bash commands in a separate context.

Use this subagent when:
- You need to run a series of related bash commands
- Terminal operations like git, npm, docker, etc.
- Command output is verbose and would clutter main context
- Build, test, or deployment operations

Do NOT use for simple single commands - use bash tool directly instead."""


def _build_default_definitions() -> list[SubagentDefinition]:
    """Build the canonical ``general-purpose`` and ``bash`` definitions.

    Mirrors the field defaults in
    ``backend.subagents.builtins.BUILTIN_SUBAGENTS``.
    """
    return [
        SubagentDefinition(
            name="general-purpose",
            description=GENERAL_PURPOSE_DESCRIPTION,
            system_prompt=GENERAL_PURPOSE_SYSTEM_PROMPT,
            tools=None,  # Inherit all tools from parent
            disallowed_tools=["task", "ask_clarification", "present_files"],
            model="inherit",
            max_turns=100,
        ),
        SubagentDefinition(
            name="bash",
            description=BASH_AGENT_DESCRIPTION,
            system_prompt=BASH_AGENT_SYSTEM_PROMPT,
            tools=["bash", "ls", "read_file", "write_file", "str_replace"],
            disallowed_tools=["task", "ask_clarification", "present_files"],
            model="inherit",
            max_turns=60,
        ),
    ]


class DeerFlowSubagentRegistry:
    """DeerFlow's built-in subagent registry (general-purpose + bash).

    Built-in roles are loaded eagerly at construction time and cannot
    be removed; :meth:`register` only adds new roles alongside the
    built-ins (it cannot replace them by default — see
    :meth:`register_override` for that).
    """

    def __init__(self) -> None:
        self._roles: dict[str, SubagentDefinition] = {}
        for definition in _build_default_definitions():
            self._roles[definition.name] = definition
        self._custom: dict[str, SubagentDefinition] = {}

    def get(self, name: str) -> SubagentDefinition | None:
        return self._roles.get(name) or self._custom.get(name)

    def list_names(self) -> list[str]:
        return sorted(set(self._roles) | set(self._custom))

    def register(self, definition: SubagentDefinition) -> None:
        """Add a custom role alongside the built-ins.

        Custom roles cannot override built-in names; use
        :meth:`register_override` for that. This protects against
        accidental clobbering of the canonical general-purpose and
        bash definitions.
        """
        if definition.name in self._roles:
            raise ValueError(
                f"{definition.name!r} is a built-in subagent; use "
                "register_override to replace it."
            )
        self._custom[definition.name] = definition

    def register_override(self, definition: SubagentDefinition) -> None:
        """Replace a built-in role (used by config.yaml layering)."""
        self._roles[definition.name] = definition
