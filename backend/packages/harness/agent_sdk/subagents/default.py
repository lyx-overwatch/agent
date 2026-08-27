"""Default SubagentRegistry — an empty registry with no built-in roles.

:class:`DefaultSubagentRegistry` is the SDK's reference registry
when no project-specific roles are needed. It returns ``None`` for
every lookup, forcing callers to register their own roles or
subclass this class.

The DeerFlow preset replaces this with
:class:`DeerFlowSubagentRegistry`, which pre-populates
``general-purpose`` and ``bash``.
"""

from __future__ import annotations

from agent_sdk.subagents.definition import SubagentDefinition


class DefaultSubagentRegistry:
    """An empty registry; projects add their own roles via :meth:`register`."""

    def __init__(self) -> None:
        self._roles: dict[str, SubagentDefinition] = {}

    def get(self, name: str) -> SubagentDefinition | None:
        return self._roles.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._roles.keys())

    def register(self, definition: SubagentDefinition) -> None:
        # Replace on duplicate to mirror the backend's "last write
        # wins" policy. Subclasses can override for stricter
        # behavior.
        self._roles[definition.name] = definition
