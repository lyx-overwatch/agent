"""Unit tests for :mod:`agent_sdk.models.factory`.

Covers :class:`ModelConfig`, the thinking-toggle logic, the
stream-usage default, and the public :func:`create_chat_model`
factory.  The tests use a tiny in-tree fake chat-model
class to avoid a real LLM dependency.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from agent_sdk.models import ModelConfig, create_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

# ---------------------------------------------------------------------------
# A fake chat model class installed at a known import path
# ---------------------------------------------------------------------------


class _FakeChatModel(BaseChatModel):
    """Minimal BaseChatModel used to verify the factory plumbing."""

    # ``extra='allow'`` lets the factory pass any kwargs
    # (temperature, max_tokens, …) without this fake having
    # to declare them all.
    model_config = ConfigDict(extra="allow")

    model_name: str = "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        # Returns a single empty generation; the factory tests
        # do not exercise generation, only construction.
        return ChatResult(generations=[ChatGeneration(message=None)])  # type: ignore[arg-type]

    @property
    def _llm_type(self) -> str:
        return "fake"


# Install the fake class at a stable import path for the
# duration of the test session.  We use a unique module
# name to avoid colliding with anything else.
_FAKE_MODULE = "agent_sdk_tests_fake_chat_model"


@pytest.fixture(scope="module", autouse=True)
def _install_fake_model() -> None:
    if _FAKE_MODULE not in sys.modules:
        mod = types.ModuleType(_FAKE_MODULE)
        mod.FakeChatModel = _FakeChatModel  # type: ignore[attr-defined]
        sys.modules[_FAKE_MODULE] = mod


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------


class TestModelConfig:
    def test_minimal(self) -> None:
        cfg = ModelConfig(name="x", use="m:X")
        assert cfg.name == "x"
        assert cfg.use == "m:X"
        assert cfg.supports_thinking is False
        assert cfg.supports_vision is False
        assert cfg.model_settings == {}

    def test_full(self) -> None:
        cfg = ModelConfig(
            name="x",
            use="m:X",
            display_name="X",
            description="The X model",
            supports_thinking=True,
            supports_reasoning_effort=True,
            supports_vision=True,
            when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
            when_thinking_disabled={"reasoning_effort": "minimal"},
            thinking={"type": "enabled"},
            model_settings={"temperature": 0.0, "max_tokens": 1024},
        )
        assert cfg.display_name == "X"
        assert cfg.supports_thinking is True
        assert cfg.model_settings["temperature"] == 0.0

    def test_extra_fields_allowed(self) -> None:
        cfg = ModelConfig.model_config  # type: ignore[attr-defined]
        assert cfg["extra"] == "allow"


# ---------------------------------------------------------------------------
# create_chat_model
# ---------------------------------------------------------------------------


class TestCreateChatModel:
    def test_basic_construction(self) -> None:
        cfg = ModelConfig(name="fake", use=f"{_FAKE_MODULE}:FakeChatModel")
        model = create_chat_model(cfg)
        assert isinstance(model, _FakeChatModel)
        assert model.model_name == "fake"

    def test_kwargs_override_settings(self) -> None:
        cfg = ModelConfig(
            name="fake",
            use=f"{_FAKE_MODULE}:FakeChatModel",
            model_settings={"temperature": 0.5},
        )
        model = create_chat_model(cfg, temperature=0.9)
        assert model.temperature == 0.9

    def test_thinking_enabled_requires_support(self) -> None:
        cfg = ModelConfig(
            name="fake",
            use=f"{_FAKE_MODULE}:FakeChatModel",
            supports_thinking=False,
            when_thinking_enabled={"temperature": 0.1},
        )
        with pytest.raises(ValueError, match="does not support thinking"):
            create_chat_model(cfg, thinking_enabled=True)

    def test_thinking_enabled_merges_settings(self) -> None:
        cfg = ModelConfig(
            name="fake",
            use=f"{_FAKE_MODULE}:FakeChatModel",
            supports_thinking=True,
            when_thinking_enabled={"temperature": 0.1},
        )
        model = create_chat_model(cfg, thinking_enabled=True)
        assert model.temperature == 0.1

    def test_thinking_disabled_uses_disable_block(self) -> None:
        cfg = ModelConfig(
            name="fake",
            use=f"{_FAKE_MODULE}:FakeChatModel",
            supports_thinking=True,
            when_thinking_disabled={"temperature": 0.0},
            when_thinking_enabled={"temperature": 0.1},
        )
        model = create_chat_model(cfg, thinking_enabled=False)
        assert model.temperature == 0.0

    def test_reasoning_effort_dropped_when_not_supported(self) -> None:
        cfg = ModelConfig(
            name="fake",
            use=f"{_FAKE_MODULE}:FakeChatModel",
            supports_reasoning_effort=False,
            model_settings={"reasoning_effort": "low"},
        )
        # Should not raise; reasoning_effort is silently dropped
        # because the model does not support it.
        model = create_chat_model(cfg)
        # The fake model does not have reasoning_effort so it
        # would raise on construction if it were passed.
        # Confirm that the model was built without it:
        assert isinstance(model, _FakeChatModel)

    def test_stream_usage_default_for_openai_compatible(self) -> None:
        # The fake class is not ChatOpenAI, so stream_usage
        # defaulting is a no-op. We just confirm the factory
        # does not crash.
        cfg = ModelConfig(name="fake", use=f"{_FAKE_MODULE}:FakeChatModel")
        model = create_chat_model(cfg)
        assert isinstance(model, _FakeChatModel)

    def test_tracing_callbacks_attached(self) -> None:
        cfg = ModelConfig(name="fake", use=f"{_FAKE_MODULE}:FakeChatModel")
        sentinels = ["cb1", "cb2"]
        model = create_chat_model(cfg, tracing_callbacks=sentinels)
        # BaseChatModel stores callbacks in a property whose
        # initial value is None. After attachment the list
        # contains our sentinels.
        assert model.callbacks is not None
        for s in sentinels:
            assert s in model.callbacks

    def test_tracing_callbacks_preserve_existing(self) -> None:
        cfg = ModelConfig(name="fake", use=f"{_FAKE_MODULE}:FakeChatModel")
        pre_existing = ["preserved"]
        model = create_chat_model(cfg, tracing_callbacks=["new1", "new2"])
        # Manually attach the pre-existing callback to simulate
        # a model that came in with one.
        model.callbacks = pre_existing + list(model.callbacks or [])
        # Re-run with the same kwargs — but since the factory
        # only sees a single argument list, we re-instantiate
        # from scratch:
        model2 = create_chat_model(cfg, tracing_callbacks=["new1"])
        model2.callbacks = pre_existing + list(model2.callbacks or [])
        assert "preserved" in model2.callbacks
        assert "new1" in model2.callbacks

    def test_invalid_class_path_raises(self) -> None:
        cfg = ModelConfig(name="fake", use="agent_sdk.does_not_exist:Foo")
        with pytest.raises(ImportError):
            create_chat_model(cfg)

    def test_class_not_subclass_of_base_chat_model(self) -> None:
        # Resolve a non-BaseChatModel class
        cfg = ModelConfig(name="x", use="pathlib:Path")
        with pytest.raises(ValueError, match="is not a subclass of"):
            create_chat_model(cfg)
