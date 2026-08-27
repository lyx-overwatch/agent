"""Integration tests for :class:`agent_sdk.presets.deerflow.DeerFlowAgent`.

These tests validate that the DeerFlow preset wires together
correctly — they do **not** require a real LLM, only mocks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _fake_chat_model():
    """Return a mock chat model that passes isinstance checks."""
    from unittest.mock import MagicMock

    model = MagicMock(name="FakeChatModel")
    # Make it pass isinstance(model, BaseChatModel) in most cases
    return model


def _minimal_overrides(tmp_path: Path) -> dict:
    """Return the minimal overrides needed for a fully-featured DeerFlowAgent."""
    return {
        "path_provider": _fake_path_provider(tmp_path),
    }


def _fake_path_provider(tmp_path: Path):
    """Create a minimal PathProvider for testing."""
    from agent_sdk.paths.default import DefaultPathProvider

    return DefaultPathProvider(base_dir=tmp_path)


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


class TestDeerFlowAgentConstruction:
    def test_constructs_with_minimal_args(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            path_provider=_fake_path_provider(tmp_path),
            # Disable features that need runtime deps we don't have
            features=None,
        )
        assert agent.model is not None
        assert agent.agent_name == "DeerFlow 2.0"

    def test_constructs_with_all_features_disabled(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent
        from agent_sdk.runtime.features import RuntimeFeatures

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            features=RuntimeFeatures(
                sandbox=False,
                memory=False,
                summarization=False,
                subagent=False,
                vision=False,
                auto_title=False,
                skills=False,
            ),
            path_provider=_fake_path_provider(tmp_path),
        )
        assert agent._feat("sandbox") is False
        assert agent._feat("subagent") is False

    def test_default_features(self) -> None:
        from agent_sdk.presets.deerflow import DEERFLOW_DEFAULT_FEATURES

        assert DEERFLOW_DEFAULT_FEATURES.sandbox is True
        assert DEERFLOW_DEFAULT_FEATURES.subagent is True
        assert DEERFLOW_DEFAULT_FEATURES.vision is True
        assert DEERFLOW_DEFAULT_FEATURES.auto_title is True
        assert DEERFLOW_DEFAULT_FEATURES.skills is True

    def test_custom_agent_name(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            agent_name="TestBot",
            path_provider=_fake_path_provider(tmp_path),
            features=None,
        )
        assert agent.agent_name == "TestBot"

    def test_path_provider_defaults_to_deerflow(self) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent
        from agent_sdk.presets.deerflow.paths import DeerFlowPathProvider

        agent = DeerFlowAgent(model=_fake_chat_model(), features=None)
        assert isinstance(agent.path_provider, DeerFlowPathProvider)

    def test_memory_schema_defaults_to_deerflow(self) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent
        from agent_sdk.presets.deerflow.memory import DeerFlowMemorySchema

        agent = DeerFlowAgent(model=_fake_chat_model(), features=None)
        assert agent.memory_schema_cls is DeerFlowMemorySchema

    def test_audit_rules_defaults_to_deerflow(self) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent
        from agent_sdk.presets.deerflow.audit import DeerFlowAuditRules

        agent = DeerFlowAgent(model=_fake_chat_model(), features=None)
        assert isinstance(agent.audit_rules, DeerFlowAuditRules)


# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------


class TestDeerFlowAgentSystemPrompt:
    def test_generates_default_prompt(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            path_provider=_fake_path_provider(tmp_path),
            features=None,
        )
        # system_prompt should be None → generated lazily from apply_prompt_template
        assert agent.system_prompt is None

    def test_custom_system_prompt(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            system_prompt="Custom prompt",
            path_provider=_fake_path_provider(tmp_path),
            features=None,
        )
        assert agent.system_prompt == "Custom prompt"

    def test_system_prompt_includes_subagent_when_enabled(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(
            agent_name="Test",
            subagent_enabled=True,
            max_concurrent_subagents=3,
        )
        assert "SUBAGENT MODE ACTIVE" in prompt
        assert "MAXIMUM 3" in prompt

    def test_system_prompt_excludes_subagent_when_disabled(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow.prompts.system import apply_prompt_template

        prompt = apply_prompt_template(
            agent_name="Test",
            subagent_enabled=False,
        )
        assert "SUBAGENT MODE ACTIVE" not in prompt


# ------------------------------------------------------------------
# Feature helpers
# ------------------------------------------------------------------


class TestDeerFlowAgentFeatures:
    def test_feat_returns_true_for_enabled(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            path_provider=_fake_path_provider(tmp_path),
            features=None,
        )
        # Default features: subagent=True
        assert agent._feat("subagent") is True

    def test_feat_returns_false_for_disabled(self, tmp_path: Path) -> None:
        from agent_sdk.presets.deerflow import DeerFlowAgent
        from agent_sdk.runtime.features import RuntimeFeatures

        agent = DeerFlowAgent(
            model=_fake_chat_model(),
            features=RuntimeFeatures(subagent=False, sandbox=False),
            path_provider=_fake_path_provider(tmp_path),
        )
        assert agent._feat("subagent") is False


# ------------------------------------------------------------------
# Graph building (with mocked create_agent)
# ------------------------------------------------------------------


class TestDeerFlowAgentGraph:
    def test_build_returns_compiled_graph(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from agent_sdk.presets.deerflow import DeerFlowAgent

        fake_graph = MagicMock(name="CompiledStateGraph")

        with patch("agent_sdk.runtime.entry.create_agent", return_value=fake_graph):
            agent = DeerFlowAgent(
                model=_fake_chat_model(),
                path_provider=_fake_path_provider(tmp_path),
                features=None,
            )
            graph = agent.graph
            assert graph is fake_graph

    def test_graph_is_cached(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from agent_sdk.presets.deerflow import DeerFlowAgent

        fake_graph = MagicMock(name="CompiledStateGraph")

        with patch("agent_sdk.runtime.entry.create_agent", return_value=fake_graph) as mock_create:
            agent = DeerFlowAgent(
                model=_fake_chat_model(),
                path_provider=_fake_path_provider(tmp_path),
                features=None,
            )
            g1 = agent.graph
            g2 = agent.graph
            assert g1 is g2
            assert mock_create.call_count == 1  # cached
