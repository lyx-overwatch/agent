"""Unit tests for :mod:`agent_sdk.presets.deerflow.prompts.system`."""

from __future__ import annotations


class TestApplyPromptTemplate:
    def test_default_output(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template()
        assert "DeerFlow 2.0" in prompt
        assert "thinking_style" in prompt
        assert "clarification_system" in prompt
        assert "working_directory" in prompt
        assert "response_style" in prompt
        assert "citations" in prompt
        assert "critical_reminders" in prompt
        assert "<current_date>" in prompt

    def test_custom_agent_name(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(agent_name="MyBot")
        assert "MyBot" in prompt

    def test_subagent_enabled(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(subagent_enabled=True)
        assert "SUBAGENT MODE ACTIVE" in prompt
        assert "HARD CONCURRENCY LIMIT" in prompt

    def test_subagent_disabled(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(subagent_enabled=False)
        assert "SUBAGENT MODE ACTIVE" not in prompt

    def test_soul_section(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(soul="<soul>\nBe helpful.\n</soul>")
        assert "Be helpful." in prompt

    def test_memory_context(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(memory_context="<memory>\nUser likes Python.\n</memory>")
        assert "User likes Python." in prompt

    def test_skills_section(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(skills_section="<skill_system>\nMy skills.\n</skill_system>")
        assert "My skills." in prompt

    def test_deferred_tools_section(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(deferred_tools_section="<available-deferred-tools>\ntool_a\n</available-deferred-tools>")
        assert "tool_a" in prompt

    def test_max_concurrent_parameter(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(subagent_enabled=True, max_concurrent_subagents=5)
        assert "MAXIMUM 5" in prompt

    def test_custom_mounts(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(custom_mounts=[("/mnt/data", False), ("/mnt/readonly", True)])
        assert "Custom Mounted Directories" in prompt
        assert "/mnt/data" in prompt
        assert "read-write" in prompt
        assert "/mnt/readonly" in prompt
        assert "read-only" in prompt

    def test_current_date_tag(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template()
        assert "<current_date>" in prompt
        # Should contain a year and day-of-week
        import datetime
        today = datetime.datetime.now()
        assert today.strftime("%Y") in prompt


class TestBuildSubagentSection:
    def test_default_output(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_subagent_section

        section = build_subagent_section()
        assert "SUBAGENT MODE ACTIVE" in section
        assert "general-purpose" in section
        assert "MAXIMUM 3" in section

    def test_custom_max_concurrent(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_subagent_section

        section = build_subagent_section(max_concurrent=4)
        assert "MAXIMUM 4" in section

    def test_bash_available(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_subagent_section

        section = build_subagent_section(bash_available=True)
        assert "bash, ls, read_file, web_search" in section

    def test_bash_unavailable(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_subagent_section

        section = build_subagent_section(bash_available=False)
        assert "bash, ls, read_file, web_search" not in section


class TestBuildSkillsPromptSection:
    def test_empty_when_no_skills(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_skills_prompt_section

        section = build_skills_prompt_section()
        assert section == ""

    def test_with_skills_xml(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_skills_prompt_section

        section = build_skills_prompt_section(skills_xml="<available_skills>\n<skill><name>test</name></skill>\n</available_skills>")
        assert "test" in section
        assert "Progressive Loading Pattern" in section

    def test_with_evolution_enabled(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_skills_prompt_section

        section = build_skills_prompt_section(skill_evolution_enabled=True)
        assert "Skill Self-Evolution" in section


class TestBuildCustomMountsSection:
    def test_empty_when_no_mounts(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_custom_mounts_section

        assert build_custom_mounts_section() == ""
        assert build_custom_mounts_section(mounts=[]) == ""

    def test_with_mounts(self) -> None:
        from agent_sdk.presets.deerflow.prompts.system import build_custom_mounts_section

        section = build_custom_mounts_section(mounts=[("/mnt/data", False)])
        assert "/mnt/data" in section
        assert "read-write" in section
