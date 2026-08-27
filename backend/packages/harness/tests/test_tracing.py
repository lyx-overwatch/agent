"""Unit tests for :mod:`agent_sdk.tracing.factory`.

Covers the configuration data classes
(:class:`TracingConfig`, :class:`LangSmithConfig`,
:class:`LangfuseConfig`) and :func:`build_tracing_callbacks`.

Provider imports are mocked because neither
``langchain_core.tracers.langchain`` (with the import
infrastructure for LangSmith) nor ``langfuse`` may be
available in the test environment.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from agent_sdk.tracing import (
    LangfuseConfig,
    LangSmithConfig,
    TracingConfig,
    build_tracing_callbacks,
)

# ---------------------------------------------------------------------------
# Fake provider modules
# ---------------------------------------------------------------------------


class _FakeLangSmithTracer:
    """Stand-in for ``langchain_core.tracers.langchain.LangChainTracer``."""

    def __init__(self, project_name: str | None = None) -> None:
        self.project_name = project_name
        self.kind = "langsmith"


class _FakeLangfuseHandler:
    """Stand-in for ``langfuse.langchain.CallbackHandler``."""

    def __init__(self, public_key: str | None = None) -> None:
        self.public_key = public_key
        self.kind = "langfuse"


@pytest.fixture(autouse=True)
def _install_fake_providers():
    """Install the fake provider modules so the factory's lazy imports succeed."""
    saved = {}
    fake_langchain = types.ModuleType("langchain_core.tracers.langchain")
    fake_langchain.LangChainTracer = _FakeLangSmithTracer  # type: ignore[attr-defined]
    saved["langchain_core.tracers.langchain"] = sys.modules.get("langchain_core.tracers.langchain")
    sys.modules["langchain_core.tracers.langchain"] = fake_langchain

    # Langfuse requires two fake modules: the top-level ``langfuse``
    # and the sub-module ``langfuse.langchain``.
    fake_langfuse = types.ModuleType("langfuse")
    fake_langfuse.Langfuse = lambda **kwargs: None  # type: ignore[attr-defined]
    fake_langfuse_chain = types.ModuleType("langfuse.langchain")
    fake_langfuse_chain.CallbackHandler = _FakeLangfuseHandler  # type: ignore[attr-defined]
    saved["langfuse"] = sys.modules.get("langfuse")
    saved["langfuse.langchain"] = sys.modules.get("langfuse.langchain")
    sys.modules["langfuse"] = fake_langfuse
    sys.modules["langfuse.langchain"] = fake_langfuse_chain

    yield

    # Restore
    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------


class TestLangSmithConfig:
    def test_defaults(self) -> None:
        cfg = LangSmithConfig()
        assert cfg.project is None

    def test_with_project(self) -> None:
        cfg = LangSmithConfig(project="my-project")
        assert cfg.project == "my-project"


class TestLangfuseConfig:
    def test_defaults(self) -> None:
        cfg = LangfuseConfig()
        assert cfg.secret_key is None
        assert cfg.public_key is None
        assert cfg.host is None

    def test_with_keys(self) -> None:
        cfg = LangfuseConfig(secret_key="sk", public_key="pk", host="https://example.com")
        assert cfg.secret_key == "sk"
        assert cfg.public_key == "pk"
        assert cfg.host == "https://example.com"


class TestTracingConfig:
    def test_defaults(self) -> None:
        cfg = TracingConfig()
        assert cfg.providers == []
        assert isinstance(cfg.langsmith, LangSmithConfig)
        assert isinstance(cfg.langfuse, LangfuseConfig)

    def test_with_providers(self) -> None:
        cfg = TracingConfig(
            providers=["langsmith", "langfuse"],
            langsmith=LangSmithConfig(project="p"),
            langfuse=LangfuseConfig(public_key="pk"),
        )
        assert cfg.providers == ["langsmith", "langfuse"]
        assert cfg.langsmith.project == "p"
        assert cfg.langfuse.public_key == "pk"

    def test_invalid_provider_rejected(self) -> None:
        with pytest.raises(ValueError):
            TracingConfig(providers=["unknown"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# build_tracing_callbacks
# ---------------------------------------------------------------------------


class TestBuildTracingCallbacks:
    def test_no_config_returns_empty(self) -> None:
        assert build_tracing_callbacks() == []

    def test_empty_providers_returns_empty(self) -> None:
        assert build_tracing_callbacks(TracingConfig()) == []

    def test_langsmith_only(self) -> None:
        cfg = TracingConfig(providers=["langsmith"], langsmith=LangSmithConfig(project="p"))
        callbacks = build_tracing_callbacks(cfg)
        assert len(callbacks) == 1
        assert callbacks[0].kind == "langsmith"
        assert callbacks[0].project_name == "p"

    def test_langfuse_only(self) -> None:
        cfg = TracingConfig(providers=["langfuse"], langfuse=LangfuseConfig(public_key="pk"))
        callbacks = build_tracing_callbacks(cfg)
        assert len(callbacks) == 1
        assert callbacks[0].kind == "langfuse"
        assert callbacks[0].public_key == "pk"

    def test_both_providers_in_order(self) -> None:
        cfg = TracingConfig(
            providers=["langsmith", "langfuse"],
            langsmith=LangSmithConfig(project="p"),
            langfuse=LangfuseConfig(public_key="pk"),
        )
        callbacks = build_tracing_callbacks(cfg)
        assert len(callbacks) == 2
        assert callbacks[0].kind == "langsmith"
        assert callbacks[1].kind == "langfuse"

    def test_raise_on_missing_raises(self) -> None:
        # If the provider init raises, raise_on_missing=True
        # re-raises as RuntimeError.
        cfg = TracingConfig(providers=["langsmith"])

        # Monkey-patch the private factory function to raise
        from agent_sdk.tracing import factory as factory_mod

        original = factory_mod._create_langsmith_tracer

        def boom(config: Any) -> Any:
            raise RuntimeError("synthetic failure")

        factory_mod._create_langsmith_tracer = boom
        try:
            with pytest.raises(RuntimeError, match="LangSmith tracing initialization failed"):
                build_tracing_callbacks(cfg, raise_on_missing=True)
        finally:
            factory_mod._create_langsmith_tracer = original

    def test_default_swallows_failures(self) -> None:
        cfg = TracingConfig(providers=["langsmith"])

        from agent_sdk.tracing import factory as factory_mod

        original = factory_mod._create_langsmith_tracer

        def boom(config: Any) -> Any:
            raise RuntimeError("synthetic failure")

        factory_mod._create_langsmith_tracer = boom
        try:
            # No raise_on_missing; failures are logged at WARNING.
            callbacks = build_tracing_callbacks(cfg)
            assert callbacks == []
        finally:
            factory_mod._create_langsmith_tracer = original

    def test_unknown_provider_is_skipped(self) -> None:
        # Bypass pydantic validation
        cfg = TracingConfig.model_construct(
            providers=["unknown_provider"],
            langsmith=LangSmithConfig(),
            langfuse=LangfuseConfig(),
        )
        callbacks = build_tracing_callbacks(cfg)
        assert callbacks == []
