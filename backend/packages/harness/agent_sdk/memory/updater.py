"""MemoryUpdater — the interface for writing new memory data.

This is a re-implementation (per ADR-010) of
``backend.agents.memory.updater.MemoryUpdater``. Stage 2's
version provides the storage-side surface (load / save / clear)
but not the LLM-driven fact extraction pipeline (that lives in
stage 5).

A caller can subclass and add their own extraction logic
without modifying the rest of the SDK.
"""

from __future__ import annotations

import copy
import logging
from typing import Generic, TypeVar

from agent_sdk.memory.schema import MemorySchema
from agent_sdk.memory.storage import MemoryStorage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=MemorySchema)


class MemoryUpdater(Generic[T]):
    """Persist memory data through a :class:`MemoryStorage`.

    Stage 2's stub: covers the data path. Stage 5 adds the
    LLM-driven extraction pipeline that calls back into
    :meth:`update_section` after a model produces a memory
    delta.
    """

    def __init__(self, schema_cls: type[T], storage: MemoryStorage[T]) -> None:
        self._schema_cls = schema_cls
        self._storage = storage

    def get_memory(self) -> T:
        return self._storage.load()

    def reload(self) -> T:
        return self._storage.reload()

    def import_memory(self, memory_data: dict) -> T:
        schema = self._schema_cls.from_dict(memory_data)
        if not self._storage.save(schema):
            raise OSError("Failed to save imported memory data")
        return self._storage.load()

    def clear(self) -> T:
        empty = self._schema_cls.empty()
        if not self._storage.save(empty):
            raise OSError("Failed to save cleared memory data")
        return self._storage.load()

    def update_section(self, section: str, summary: str) -> T:
        """Update a single section in the schema and persist.

        Args:
            section: The schema path, e.g. ``"user.workContext"`` or
                ``"history.recentMonths"``.
            summary: The new summary text.
        """
        schema = self._storage.load()
        data = schema.to_dict()
        path = section.split(".")
        cursor: object = data
        for key in path[:-1]:
            if not isinstance(cursor, dict) or key not in cursor:
                raise KeyError(f"Section {section!r} not found in schema")
            cursor = cursor[key]  # type: ignore[index]
        if not isinstance(cursor, dict) or path[-1] not in cursor:
            raise KeyError(f"Section {section!r} not found in schema")
        if isinstance(cursor[path[-1]], dict) and "summary" in cursor[path[-1]]:  # type: ignore[index]
            from datetime import UTC, datetime

            cursor[path[-1]]["summary"] = summary  # type: ignore[index]
            cursor[path[-1]]["updatedAt"] = datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"  # type: ignore[index]
        else:
            cursor[path[-1]] = summary  # type: ignore[index]
        new_schema = self._schema_cls.from_dict(copy.deepcopy(data))
        new_schema.touch()  # type: ignore[attr-defined]
        if not self._storage.save(new_schema):
            raise OSError(f"Failed to save updated section {section!r}")
        return new_schema
