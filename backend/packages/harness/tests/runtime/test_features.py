"""Unit tests for :class:`agent_sdk.runtime.features.RuntimeFeatures`.

Covers the default values, the three-way ``True``/``False``/instance
contract, and the :meth:`is_enabled` helper.
"""

from __future__ import annotations

from agent_sdk.runtime.features import RuntimeFeatures
from langchain.agents.middleware import AgentMiddleware


class _NoopMiddleware(AgentMiddleware):
    """A trivial :class:`AgentMiddleware` for the custom-instance tests."""


class TestRuntimeFeaturesDefaults:
    def test_default_sandbox_is_true_in_5_6(self) -> None:
        # Stage 5.6 flipped the default to ``True`` to match the
        # original ``create_deerflow_agent`` contract. Callers
        # that have no PathProvider / SandboxProvider should pass
        # ``sandbox=False`` explicitly.
        assert RuntimeFeatures().sandbox is True

    def test_default_memory_is_false(self) -> None:
        assert RuntimeFeatures().memory is False

    def test_default_summarization_is_false(self) -> None:
        assert RuntimeFeatures().summarization is False

    def test_default_subagent_is_false(self) -> None:
        assert RuntimeFeatures().subagent is False

    def test_default_vision_is_false(self) -> None:
        assert RuntimeFeatures().vision is False

    def test_default_auto_title_is_false(self) -> None:
        assert RuntimeFeatures().auto_title is False

class TestRuntimeFeaturesContract:
    def test_can_set_each_field_to_true(self) -> None:
        f = RuntimeFeatures(sandbox=True, memory=True, summarization=False)
        assert f.sandbox is True
        assert f.memory is True
        assert f.summarization is False

    def test_can_set_each_field_to_false(self) -> None:
        f = RuntimeFeatures(sandbox=False, memory=False)
        assert f.sandbox is False
        assert f.memory is False

    def test_can_set_each_field_to_instance(self) -> None:
        custom = _NoopMiddleware()
        f = RuntimeFeatures(memory=custom)
        assert f.memory is custom

    def test_summarization_accepts_instance(self) -> None:
        # summarization has no built-in default but accepts a custom
        # AgentMiddleware instance.
        custom = _NoopMiddleware()
        f = RuntimeFeatures(summarization=custom)  # type: ignore[arg-type]
        assert f.summarization is custom

class TestIsEnabled:
    def test_default_features_in_5_6(self) -> None:
        # In 5.6, ``sandbox`` flipped to ``True`` (matching the
        # backend ``create_deerflow_agent`` contract); the other
        # features still default to ``False`` because the feature
        # layer for each is opt-in. The always-on chain
        # (DanglingToolCall / ToolErrorHandling / LoopDetection)
        # is always-on regardless of these flags.
        f = RuntimeFeatures()
        assert f.is_enabled("sandbox") is True
        for name in (
            "memory",
            "summarization",
            "subagent",
            "vision",
            "auto_title",
            "skills",
        ):
            assert f.is_enabled(name) is False, name

    def test_custom_instance_counts_as_enabled(self) -> None:
        f = RuntimeFeatures(memory=_NoopMiddleware())
        assert f.is_enabled("memory") is True

    def test_explicit_true_counts_as_enabled(self) -> None:
        f = RuntimeFeatures(subagent=True)
        assert f.is_enabled("subagent") is True

    def test_unknown_name_returns_false(self) -> None:
        # ``is_enabled`` is defensive: an unknown name returns
        # ``False`` rather than raising.
        assert RuntimeFeatures().is_enabled("nope") is False
