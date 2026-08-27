"""Unit tests for :class:`agent_sdk.subagents.default.DefaultSubagentRegistry`."""

from __future__ import annotations

from agent_sdk.subagents.default import DefaultSubagentRegistry
from agent_sdk.subagents.definition import SubagentDefinition


class TestEmptyRegistry:
    def test_empty_lookup_returns_none(self) -> None:
        registry = DefaultSubagentRegistry()
        assert registry.get("general-purpose") is None

    def test_empty_list_names(self) -> None:
        registry = DefaultSubagentRegistry()
        assert registry.list_names() == []


class TestRegister:
    def test_register_adds_role(self) -> None:
        registry = DefaultSubagentRegistry()
        role = SubagentDefinition(name="custom", description="x", system_prompt="y")
        registry.register(role)
        assert registry.get("custom") == role
        assert "custom" in registry.list_names()

    def test_register_replaces_duplicate(self) -> None:
        registry = DefaultSubagentRegistry()
        role1 = SubagentDefinition(name="custom", description="v1", system_prompt="y")
        role2 = SubagentDefinition(name="custom", description="v2", system_prompt="y")
        registry.register(role1)
        registry.register(role2)
        assert registry.get("custom").description == "v2"

    def test_list_names_is_sorted(self) -> None:
        registry = DefaultSubagentRegistry()
        for name in ("zebra", "alpha", "mango"):
            registry.register(SubagentDefinition(name=name, description="x", system_prompt="y"))
        assert registry.list_names() == ["alpha", "mango", "zebra"]
