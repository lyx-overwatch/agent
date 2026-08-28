"""Tests for :func:`app.core.subagent_registry.build_skillhub_registry`."""

from __future__ import annotations

from app.core.subagent_registry import (
    build_skillhub_registry,
)


class TestBuiltInRoles:
    def test_general_purpose_is_registered(self) -> None:
        """general-purpose role is available."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert definition is not None
        assert definition.name == "general-purpose"

    def test_bash_is_registered(self) -> None:
        """bash role is available."""
        registry = build_skillhub_registry()
        definition = registry.get("bash")
        assert definition is not None
        assert definition.name == "bash"

    def test_list_names_contains_both(self) -> None:
        """list_names returns both built-in roles."""
        registry = build_skillhub_registry()
        names = registry.list_names()
        assert "general-purpose" in names
        assert "bash" in names

    def test_unknown_role_returns_none(self) -> None:
        """Unknown role names return None."""
        registry = build_skillhub_registry()
        assert registry.get("nonexistent") is None


class TestGeneralPurposeRole:
    def test_inherits_all_tools(self) -> None:
        """tools=None to inherit parent tools."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert definition.tools is None

    def test_disallows_nesting_tools(self) -> None:
        """task, ask_clarification, present_files are denied."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert "task" in definition.disallowed_tools
        assert "ask_clarification" in definition.disallowed_tools
        assert "present_files" in definition.disallowed_tools

    def test_inherits_model(self) -> None:
        """model='inherit' to use parent model."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert definition.model == "inherit"

    def test_max_turns(self) -> None:
        """general-purpose gets higher max_turns."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert definition.max_turns == 100

    def test_system_prompt_mentions_skillhub_workspace(self) -> None:
        """System prompt references Heyu Agent workspace paths."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert "/mnt/user-data/workspace" in definition.system_prompt
        assert "/mnt/user-data/outputs" in definition.system_prompt
        assert "/mnt/skills" in definition.system_prompt

    def test_system_prompt_does_not_mention_deerflow(self) -> None:
        """System prompt is Heyu Agent-native, no DeerFlow branding."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert "DeerFlow" not in definition.system_prompt
        assert "deerflow" not in definition.system_prompt

    def test_description_mentions_complex_tasks(self) -> None:
        """Description is useful for the LLM to decide when to delegate."""
        registry = build_skillhub_registry()
        definition = registry.get("general-purpose")
        assert len(definition.description) > 20


class TestBashRole:
    def test_restricts_tools(self) -> None:
        """Bash subagent only gets sandbox tools."""
        registry = build_skillhub_registry()
        definition = registry.get("bash")
        assert "bash" in definition.tools
        assert "ls" in definition.tools
        assert "read_file" in definition.tools
        assert "write_file" in definition.tools
        assert "str_replace" in definition.tools
        # Does NOT have unrestricted access
        assert definition.tools is not None

    def test_max_turns(self) -> None:
        """bash gets fewer turns than general-purpose."""
        registry = build_skillhub_registry()
        definition = registry.get("bash")
        assert definition.max_turns == 60

    def test_system_prompt_mentions_skillhub_workspace(self) -> None:
        """System prompt references Heyu Agent workspace paths."""
        registry = build_skillhub_registry()
        definition = registry.get("bash")
        assert "/mnt/user-data/workspace" in definition.system_prompt

    def test_disallows_nesting(self) -> None:
        """Bash subagent cannot spawn further subagents."""
        registry = build_skillhub_registry()
        definition = registry.get("bash")
        assert "task" in definition.disallowed_tools


class TestCustomRoles:
    def test_custom_role_is_added(self) -> None:
        """Custom roles from config are added alongside built-ins."""
        registry = build_skillhub_registry(
            custom_roles={
                "code-reviewer": {
                    "description": "Reviews code for issues",
                    "system_prompt": "You are a code reviewer.",
                }
            }
        )
        definition = registry.get("code-reviewer")
        assert definition is not None
        assert definition.name == "code-reviewer"
        assert definition.description == "Reviews code for issues"
        assert definition.system_prompt == "You are a code reviewer."

    def test_custom_role_overrides_builtin(self) -> None:
        """Custom role with same name as built-in overrides it (last write wins)."""
        registry = build_skillhub_registry(
            custom_roles={
                "bash": {
                    "description": "My custom bash agent",
                    "system_prompt": "Custom bash prompt.",
                }
            }
        )
        definition = registry.get("bash")
        assert definition is not None
        assert definition.description == "My custom bash agent"
        assert definition.system_prompt == "Custom bash prompt."

    def test_custom_role_default_values(self) -> None:
        """Unspecified custom role fields get sensible defaults."""
        registry = build_skillhub_registry(
            custom_roles={
                "minimal": {
                    "description": "Minimal role",
                    "system_prompt": "You are minimal.",
                }
            }
        )
        definition = registry.get("minimal")
        assert definition.tools is None  # default in build_skillhub_registry
        assert definition.model == "inherit"
        assert definition.max_turns == 50
        assert definition.timeout_seconds == 900

    def test_builtins_remain_when_custom_added(self) -> None:
        """Built-in roles are not affected by custom role additions."""
        registry = build_skillhub_registry(
            custom_roles={
                "custom-role": {
                    "description": "A custom role",
                    "system_prompt": "You are custom.",
                }
            }
        )
        assert registry.get("general-purpose") is not None
        assert registry.get("bash") is not None
        assert registry.get("custom-role") is not None

    def test_no_custom_roles_still_has_builtins(self) -> None:
        """build_skillhub_registry() with no args has all 5 built-in roles."""
        registry = build_skillhub_registry()
        names = registry.list_names()
        assert "general-purpose" in names
        assert "bash" in names
        assert "skill-scaffolder" in names
        assert "skill-tester" in names
        assert "skill-reviewer" in names
        assert len(names) == 5
