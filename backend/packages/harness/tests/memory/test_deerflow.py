"""Unit tests for :class:`agent_sdk.presets.deerflow.DeerFlowMemorySchema`.

Verifies byte-level compatibility with
``backend.agents.memory.storage.create_empty_memory()`` and the
three-section user profile / conversation history shape.
"""

from __future__ import annotations

from agent_sdk.presets.deerflow.memory import DeerFlowMemorySchema, _empty_deerflow_dict


class TestDeerFlowMemorySchemaEmpty:
    def test_empty_dict_is_byte_equivalent_to_backend(self) -> None:
        """The empty dict shape MUST match the backend's
        ``create_empty_memory()`` byte-for-byte.
        """
        expected = {
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
        assert _empty_deerflow_dict() == expected

    def test_empty_factory(self) -> None:
        schema = DeerFlowMemorySchema.empty()
        assert schema.to_dict() == _empty_deerflow_dict()

    def test_construction_with_none(self) -> None:
        schema = DeerFlowMemorySchema()
        assert schema.to_dict() == _empty_deerflow_dict()


class TestDeerFlowMemorySchemaGetUserProfile:
    def test_returns_three_section_mapping(self) -> None:
        schema = DeerFlowMemorySchema(
            {
                "user": {
                    "workContext": {"summary": "Engineer at Acme", "updatedAt": ""},
                    "personalContext": {"summary": "Lives in NYC", "updatedAt": ""},
                    "topOfMind": {"summary": "Buying a house", "updatedAt": ""},
                },
            }
        )
        assert schema.get_user_profile() == {
            "work_context": "Engineer at Acme",
            "personal_context": "Lives in NYC",
            "top_of_mind": "Buying a house",
        }

    def test_missing_sections_default_to_empty(self) -> None:
        schema = DeerFlowMemorySchema.empty()
        assert schema.get_user_profile() == {
            "work_context": "",
            "personal_context": "",
            "top_of_mind": "",
        }


class TestDeerFlowMemorySchemaGetConversationHistory:
    def test_returns_three_period_mapping(self) -> None:
        schema = DeerFlowMemorySchema(
            {
                "history": {
                    "recentMonths": {"summary": "Discussed Acme project", "updatedAt": ""},
                    "earlierContext": {"summary": "Talked about moving", "updatedAt": ""},
                    "longTermBackground": {"summary": "User is a long-time customer", "updatedAt": ""},
                },
            }
        )
        assert schema.get_conversation_history() == [
            {"period": "recent_months", "summary": "Discussed Acme project"},
            {"period": "earlier_context", "summary": "Talked about moving"},
            {"period": "long_term", "summary": "User is a long-time customer"},
        ]

    def test_empty_history(self) -> None:
        schema = DeerFlowMemorySchema.empty()
        assert schema.get_conversation_history() == [
            {"period": "recent_months", "summary": ""},
            {"period": "earlier_context", "summary": ""},
            {"period": "long_term", "summary": ""},
        ]


class TestDeerFlowMemorySchemaRoundTrip:
    def test_to_dict_then_from_dict(self) -> None:
        original = DeerFlowMemorySchema(
            {
                "user": {
                    "workContext": {"summary": "w", "updatedAt": "t1"},
                    "personalContext": {"summary": "p", "updatedAt": "t2"},
                    "topOfMind": {"summary": "m", "updatedAt": "t3"},
                },
                "history": {
                    "recentMonths": {"summary": "r", "updatedAt": "t4"},
                    "earlierContext": {"summary": "e", "updatedAt": "t5"},
                    "longTermBackground": {"summary": "l", "updatedAt": "t6"},
                },
                "facts": [{"text": "f1", "addedAt": "t7"}],
            }
        )
        d = original.to_dict()
        restored = DeerFlowMemorySchema.from_dict(d)
        assert restored.to_dict() == d

    def test_to_dict_is_deep_copy(self) -> None:
        schema = DeerFlowMemorySchema()
        d1 = schema.to_dict()
        d1["user"]["workContext"]["summary"] = "mutated"
        d2 = schema.to_dict()
        assert d2["user"]["workContext"]["summary"] == ""


class TestDeerFlowMemorySchemaForwardCompat:
    def test_unknown_top_level_keys_preserved(self) -> None:
        data: dict = {"facts": [], "future_field": "future_value"}
        schema = DeerFlowMemorySchema(data)
        assert schema.to_dict()["future_field"] == "future_value"

    def test_partial_data_fills_defaults(self) -> None:
        schema = DeerFlowMemorySchema({"user": {"workContext": {"summary": "w", "updatedAt": ""}}})
        d = schema.to_dict()
        assert d["user"]["personalContext"]["summary"] == ""  # default filled
        assert d["history"]["recentMonths"]["summary"] == ""  # default filled
        assert d["facts"] == []  # default filled


class TestDeerFlowMemorySchemaTouch:
    def test_touch_updates_last_updated(self) -> None:
        schema = DeerFlowMemorySchema.empty()
        assert schema.to_dict()["lastUpdated"] == ""
        schema.touch()
        ts = schema.to_dict()["lastUpdated"]
        assert ts.endswith("Z")
