"""SubagentRegistry Protocol.

A :class:`SubagentRegistry` is the brand-neutral injection point for
the subagent role table. The runtime consults it via the ``task``
tool when the parent agent wants to delegate work.

The Protocol is intentionally minimal:

* :meth:`get` — look up a role by name
* :meth:`list_names` — enumerate available role names
* :meth:`register` — add a custom role at runtime

Implementations decide whether roles are read-only (e.g. the
DeerFlow preset) or mutable (e.g. a registry that loads from
``config.yaml`` and supports custom additions).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_sdk.subagents.definition import SubagentDefinition


@runtime_checkable
class SubagentRegistry(Protocol):
    """Registry of available subagent types."""

    def get(self, name: str) -> SubagentDefinition | None:
        """Look up a subagent definition by name.

        Returns ``None`` if no role with that name is registered.
        """
        ...

    def list_names(self) -> list[str]:
        """List all available subagent names."""
        ...

    def register(self, definition: SubagentDefinition) -> None:
        """Register a new subagent (custom or override).

        Implementations may reject duplicate names or replace
        existing roles; the contract does not require a specific
        policy.
        """
        ...
