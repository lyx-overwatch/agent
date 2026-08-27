"""MemorySchema Protocol.

A :class:`MemorySchema` is the brand-neutral injection point for the
long-term memory data model. It defines how memory data is shaped
*as seen by the runtime* (system prompt injection, history recall,
fact extraction) and how it is serialized to a backing
:class:`MemoryStorage`.

The Protocol surface is intentionally minimal:

* :meth:`to_dict` / :meth:`from_dict` — wire format
* :meth:`get_user_profile` — what to inject as the user-level
  context into the system prompt
* :meth:`get_conversation_history` — what to inject as past
  conversation summary
* :meth:`empty` — a factory for an empty schema, used when no
  memory exists yet

Implementations are free to choose any data model. The DeerFlow
preset uses the three-section model (``user.{workContext,
personalContext, topOfMind}`` + ``history.{recentMonths,
earlierContext, longTermBackground}`` + ``facts: list``), while a
fresh project can use any shape it likes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemorySchema(Protocol):
    """Long-term memory data model.

    Implementations are immutable from the runtime's perspective:
    the runtime calls :meth:`to_dict` to serialize, persists via
    :meth:`MemoryStorage.save`, and re-loads via
    :meth:`from_dict`. The schema instance itself is a value
    object.
    """

    def to_dict(self) -> dict[str, Any]:
        """Serialize the memory data to a dict for storage."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemorySchema:
        """Deserialize memory data from storage.

        Implementations MUST be tolerant of unknown keys (forward
        compatibility) and missing keys (older payloads).
        """
        ...

    def get_user_profile(self) -> dict[str, str]:
        """Return the user-level profile injected into the system prompt.

        Returns a mapping of named slots to short text summaries.
        Implementations decide the slot names; the runtime does not
        inspect them.
        """
        ...

    def get_conversation_history(self) -> list[dict[str, str]]:
        """Return past conversation summaries as a list of records.

        Each record is a free-form ``{period: str, summary: str}``-style
        mapping. The runtime injects them as a chronological list.
        """
        ...

    @classmethod
    def empty(cls) -> MemorySchema:
        """Return an empty schema, used for first-run agents."""
        ...
