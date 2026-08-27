"""Unit tests for :class:`agent_sdk.memory.storage.MemoryStorage`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_sdk.memory.default import DefaultMemorySchema
from agent_sdk.memory.storage import FileMemoryStorage
from agent_sdk.presets.deerflow.memory import DeerFlowMemorySchema


class TestFileMemoryStorageWithDefaultSchema:
    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileMemoryStorage[DefaultMemorySchema]:
        return FileMemoryStorage(tmp_path / "memory.json", DefaultMemorySchema)

    def test_empty_file_returns_empty_schema(self, storage: FileMemoryStorage[DefaultMemorySchema]) -> None:
        schema = storage.load()
        assert schema.to_dict()["notes"] == ""

    def test_save_and_load_round_trip(self, storage: FileMemoryStorage[DefaultMemorySchema]) -> None:
        schema = DefaultMemorySchema({"notes": "hello", "facts": [{"text": "f1", "addedAt": ""}]})
        assert storage.save(schema) is True
        loaded = storage.load()
        assert loaded.get_user_profile() == {"notes": "hello"}

    def test_save_creates_file(self, storage: FileMemoryStorage[DefaultMemorySchema], tmp_path: Path) -> None:
        storage.save(DefaultMemorySchema({"notes": "x"}))
        assert (tmp_path / "memory.json").exists()

    def test_reload_skips_cache(self, storage: FileMemoryStorage[DefaultMemorySchema], tmp_path: Path) -> None:
        # Seed the file externally
        (tmp_path / "memory.json").write_text(
            json.dumps({"version": "1.0", "lastUpdated": "", "notes": "external", "facts": []}),
            encoding="utf-8",
        )
        loaded = storage.reload()
        assert loaded.get_user_profile() == {"notes": "external"}


class TestFileMemoryStorageWithDeerFlowSchema:
    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileMemoryStorage[DeerFlowMemorySchema]:
        return FileMemoryStorage(tmp_path / "memory.json", DeerFlowMemorySchema)

    def test_save_and_load_preserves_three_section_shape(
        self, storage: FileMemoryStorage[DeerFlowMemorySchema]
    ) -> None:
        schema = DeerFlowMemorySchema(
            {
                "user": {
                    "workContext": {"summary": "engineer", "updatedAt": "t"},
                    "personalContext": {"summary": "p", "updatedAt": ""},
                    "topOfMind": {"summary": "m", "updatedAt": ""},
                },
                "history": {
                    "recentMonths": {"summary": "r", "updatedAt": ""},
                    "earlierContext": {"summary": "e", "updatedAt": ""},
                    "longTermBackground": {"summary": "l", "updatedAt": ""},
                },
                "facts": [],
            }
        )
        storage.save(schema)
        loaded = storage.load()
        assert loaded.get_user_profile() == {
            "work_context": "engineer",
            "personal_context": "p",
            "top_of_mind": "m",
        }

    def test_empty_file_returns_empty_deerflow_schema(
        self, storage: FileMemoryStorage[DeerFlowMemorySchema]
    ) -> None:
        loaded = storage.load()
        assert loaded.get_user_profile() == {
            "work_context": "",
            "personal_context": "",
            "top_of_mind": "",
        }
