"""DeerFlow preset: MemorySchema preserving the three-section model.

:class:`DeerFlowMemorySchema` preserves the
``workContext / personalContext / topOfMind`` (user) +
``recentMonths / earlierContext / longTermBackground`` (history) +
``facts: list`` data model from
``backend.agents.memory.storage.create_empty_memory()``.

The implementation is a re-implementation (per ADR-010) of the
backend logic. It must produce a byte-for-byte equivalent
``to_dict()`` for the empty / populated cases that the backend
produces, which is verified by golden fixtures in
``tests/fixtures/memory/``.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def _empty_deerflow_dict() -> dict[str, Any]:
    """The exact empty memory dict the backend ``create_empty_memory()`` produces.

    The ``lastUpdated`` field is left empty for the empty fixture;
    a populated schema will fill it in.
    """
    return {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class DeerFlowMemorySchema:
    """DeerFlow's three-section memory data model.

    Shape (byte-equivalent to ``backend.agents.memory.storage.create_empty_memory()``)::

        {
            "version": "1.0",
            "lastUpdated": "<iso8601-Z>",
            "user": {
                "workContext":      {"summary": "...", "updatedAt": "..."},
                "personalContext":  {"summary": "...", "updatedAt": "..."},
                "topOfMind":        {"summary": "...", "updatedAt": "..."},
            },
            "history": {
                "recentMonths":       {"summary": "...", "updatedAt": "..."},
                "earlierContext":     {"summary": "...", "updatedAt": "..."},
                "longTermBackground": {"summary": "...", "updatedAt": "..."},
            },
            "facts": [{"text": "...", "addedAt": "..."}, ...],
        }
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = copy.deepcopy(data) if data is not None else _empty_deerflow_dict()
        self._fill_defaults()

    def _fill_defaults(self) -> None:
        """Ensure all known sections exist; tolerate unknown keys."""
        empty = _empty_deerflow_dict()
        self._data.setdefault("version", empty["version"])
        self._data.setdefault("lastUpdated", empty["lastUpdated"])
        self._data.setdefault("facts", [])
        for section in ("user", "history"):
            self._data.setdefault(section, {})
            for slot, defaults in empty[section].items():
                self._data[section].setdefault(slot, copy.deepcopy(defaults))

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeerFlowMemorySchema:
        return cls(data)

    def get_user_profile(self) -> dict[str, str]:
        user = self._data.get("user", {})
        return {
            "work_context": user.get("workContext", {}).get("summary", ""),
            "personal_context": user.get("personalContext", {}).get("summary", ""),
            "top_of_mind": user.get("topOfMind", {}).get("summary", ""),
        }

    def get_conversation_history(self) -> list[dict[str, str]]:
        history = self._data.get("history", {})
        return [
            {"period": "recent_months", "summary": history.get("recentMonths", {}).get("summary", "")},
            {"period": "earlier_context", "summary": history.get("earlierContext", {}).get("summary", "")},
            {"period": "long_term", "summary": history.get("longTermBackground", {}).get("summary", "")},
        ]

    @classmethod
    def empty(cls) -> DeerFlowMemorySchema:
        return cls(_empty_deerflow_dict())

    def touch(self) -> None:
        """Update ``lastUpdated`` to the current UTC time."""
        self._data["lastUpdated"] = _utc_now_iso_z()
