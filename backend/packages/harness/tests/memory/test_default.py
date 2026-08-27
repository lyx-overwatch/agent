"""Unit tests for :class:`agent_sdk.memory.default.DefaultMemorySchema`."""

from __future__ import annotations

from agent_sdk.memory.default import DefaultMemorySchema


class TestDefaultMemorySchemaBasics:
    def test_empty_has_expected_shape(self) -> None:
        schema = DefaultMemorySchema.empty()
        d = schema.to_dict()
        assert d["version"] == "1.0"
        assert d["lastUpdated"] == ""
        assert d["notes"] == ""
        assert d["facts"] == []

    def test_construction_with_none_uses_empty(self) -> None:
        schema = DefaultMemorySchema()
        assert schema.to_dict() == DefaultMemorySchema.empty().to_dict()

    def test_construction_with_data_preserves_keys(self) -> None:
        data = {"version": "1.0", "notes": "hello", "facts": [{"text": "a", "addedAt": ""}]}
        schema = DefaultMemorySchema(data)
        assert schema.get_user_profile() == {"notes": "hello"}

    def test_forward_compat_unknown_keys_preserved(self) -> None:
        data = {"notes": "x", "future_key": "future_value"}
        schema = DefaultMemorySchema(data)
        d = schema.to_dict()
        assert d["future_key"] == "future_value"

    def test_missing_keys_filled_in(self) -> None:
        data: dict = {"notes": "x"}
        schema = DefaultMemorySchema(data)
        d = schema.to_dict()
        assert d["facts"] == []  # filled in
        assert d["version"] == "1.0"  # filled in


class TestDefaultMemorySchemaRoundTrip:
    def test_to_dict_then_from_dict_round_trip(self) -> None:
        original = DefaultMemorySchema({"notes": "test", "facts": [{"text": "f1", "addedAt": "t1"}]})
        d = original.to_dict()
        restored = DefaultMemorySchema.from_dict(d)
        assert restored.to_dict() == d

    def test_to_dict_returns_deep_copy(self) -> None:
        schema = DefaultMemorySchema()
        d1 = schema.to_dict()
        d1["notes"] = "mutated"
        d2 = schema.to_dict()
        assert d2["notes"] == ""  # internal state unchanged


class TestDefaultMemorySchemaUserProfile:
    def test_get_user_profile_returns_notes(self) -> None:
        schema = DefaultMemorySchema({"notes": "loves Python"})
        assert schema.get_user_profile() == {"notes": "loves Python"}

    def test_get_user_profile_with_empty_notes(self) -> None:
        schema = DefaultMemorySchema.empty()
        assert schema.get_user_profile() == {"notes": ""}


class TestDefaultMemorySchemaConversationHistory:
    def test_default_history_is_empty(self) -> None:
        schema = DefaultMemorySchema.empty()
        assert schema.get_conversation_history() == []


class TestDefaultMemorySchemaTouch:
    def test_touch_updates_last_updated(self) -> None:
        schema = DefaultMemorySchema.empty()
        assert schema.to_dict()["lastUpdated"] == ""
        schema.touch()
        ts = schema.to_dict()["lastUpdated"]
        assert ts.endswith("Z")
        assert "T" in ts  # ISO-8601
