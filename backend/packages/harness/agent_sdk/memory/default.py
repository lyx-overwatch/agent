"""Default MemorySchema — a free-form, brand-neutral memory bag.

:class:`DefaultMemorySchema` is the SDK's reference implementation
for a memory schema. It uses a flat ``{"notes": "...", "facts":
[]}`` shape with no product-specific structure.

A fresh project adopting the SDK can use this as-is, or override
``get_user_profile`` / ``get_conversation_history`` to suit its
own data model. The DeerFlow preset replaces this with
:class:`DeerFlowMemorySchema`, which has the three-section model.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def _empty_default_dict() -> dict[str, Any]:
    return {
        "version": "1.0",
        "lastUpdated": "",
        "notes": "",
        "facts": [],
    }


class DefaultMemorySchema:
    """A free-form memory schema with no product assumptions.

    Shape::

        {
            "version": "1.0",
            "lastUpdated": "<iso8601>",
            "notes": "<free-form text>",
            "facts": [{"text": "...", "addedAt": "<iso8601>"}, ...],
        }

    This is intentionally generic. A project that wants
    structured memory should subclass and override
    :meth:`get_user_profile` / :meth:`get_conversation_history`.
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = copy.deepcopy(data) if data is not None else _empty_default_dict()
        # Forward-compat: fill in any missing keys.
        for key, value in _empty_default_dict().items():
            self._data.setdefault(key, copy.deepcopy(value))

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DefaultMemorySchema:
        return cls(data)

    def get_user_profile(self) -> dict[str, str]:
        return {"notes": self._data.get("notes", "")}

    def get_conversation_history(self) -> list[dict[str, str]]:
        return []

    @classmethod
    def empty(cls) -> DefaultMemorySchema:
        return cls(_empty_default_dict())

    def touch(self) -> None:
        """Update ``lastUpdated`` to the current UTC time."""
        self._data["lastUpdated"] = _utc_now_iso_z()
