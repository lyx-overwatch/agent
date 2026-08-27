"""Unit tests for :class:`agent_sdk.presets.deerflow.DeerFlowSubagentRegistry`."""

from __future__ import annotations

import pytest
from agent_sdk.presets.deerflow.subagents import DeerFlowSubagentRegistry
from agent_sdk.subagents.definition import SubagentDefinition


class TestBuiltinRoles:
    def test_general_purpose_role_is_registered(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert role is not None
        assert role.name == "general-purpose"

    def test_bash_role_is_registered(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("bash")
        assert role is not None
        assert role.name == "bash"

    def test_list_names_contains_both(self) -> None:
        registry = DeerFlowSubagentRegistry()
        names = registry.list_names()
        assert "general-purpose" in names
        assert "bash" in names


class TestGeneralPurposeRole:
    def test_inherits_all_tools(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert role.tools is None  # Inherit from parent

    def test_denies_task_ask_clarification_present_files(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert "task" in role.disallowed_tools
        assert "ask_clarification" in role.disallowed_tools
        assert "present_files" in role.disallowed_tools

    def test_inherits_model(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert role.model == "inherit"

    def test_max_turns(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert role.max_turns == 100

    def test_description_mentions_complex_tasks(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert "multi-step" in role.description

    def test_system_prompt_mentions_mnt_user_data(self) -> None:
        # The role's prompt references the DeerFlow virtual path;
        # this is the canonical content per the backend
        # ``BUILTIN_SUBAGENTS``.
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert "/mnt/user-data/uploads" in role.system_prompt
        assert "/mnt/user-data/workspace" in role.system_prompt
        assert "/mnt/user-data/outputs" in role.system_prompt

    def test_system_prompt_includes_output_format(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("general-purpose")
        assert "<output_format>" in role.system_prompt
        assert "<guidelines>" in role.system_prompt


class TestBashRole:
    def test_restricts_to_sandbox_tools(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("bash")
        assert role.tools is not None
        assert "bash" in role.tools
        assert "read_file" in role.tools
        assert "write_file" in role.tools

    def test_max_turns(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("bash")
        assert role.max_turns == 60

    def test_description_mentions_command_execution(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("bash")
        assert "command execution" in role.description or "bash" in role.description

    def test_system_prompt_mentions_mnt_user_data(self) -> None:
        registry = DeerFlowSubagentRegistry()
        role = registry.get("bash")
        assert "/mnt/user-data" in role.system_prompt


class TestCustomRegistration:
    def test_register_custom_role_alongside_builtins(self) -> None:
        registry = DeerFlowSubagentRegistry()
        custom = SubagentDefinition(
            name="researcher", description="Web research specialist", system_prompt="You research."
        )
        registry.register(custom)
        assert registry.get("researcher") == custom
        assert "researcher" in registry.list_names()
        assert "general-purpose" in registry.list_names()  # built-ins still present

    def test_register_rejects_builtin_name(self) -> None:
        registry = DeerFlowSubagentRegistry()
        with pytest.raises(ValueError, match="built-in"):
            registry.register(
                SubagentDefinition(name="bash", description="override", system_prompt="x")
            )

    def test_register_override_replaces_builtin(self) -> None:
        registry = DeerFlowSubagentRegistry()
        custom = SubagentDefinition(name="bash", description="custom bash", system_prompt="x")
        registry.register_override(custom)
        assert registry.get("bash").description == "custom bash"

    def test_get_returns_custom_after_builtin_override(self) -> None:
        registry = DeerFlowSubagentRegistry()
        registry.register_override(
            SubagentDefinition(name="bash", description="custom", system_prompt="x")
        )
        assert registry.get("bash").description == "custom"
