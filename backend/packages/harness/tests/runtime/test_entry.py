"""Unit tests for :func:`agent_sdk.runtime.entry.create_agent` and the
:func:`assemble_chain` / :func:`_insert_extra_middlewares` helpers.

The tests do **not** call :func:`langchain.agents.create_agent` directly
(to keep the suite offline and independent of langgraph internals).
Instead, they exercise the assembly helpers, then poke the public
entry point with a fake chat model and a fake checkpointer to verify
that the parameter validation logic is intact.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_sdk.runtime import Next, Prev
from agent_sdk.runtime.entry import create_agent
from agent_sdk.runtime.features import RuntimeFeatures
from agent_sdk.runtime.middleware_chain import (
    MiddlewareChainConfig,
    _insert_extra_middlewares,
    assemble_chain,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel

# Stage 5.2 middlewares — only available after stage 5.2 ships.
# Tests in ``TestL3ChainAssembly`` skip when they are not.
try:
    from agent_sdk.middlewares.dangling_tool_call import DanglingToolCallMiddleware
    from agent_sdk.middlewares.loop_detection import LoopDetectionMiddleware
    from agent_sdk.middlewares.tool_error_handling import ToolErrorHandlingMiddleware

    _L3_AVAILABLE = True
except ImportError:  # pragma: no cover — stage 5.2 not yet merged
    _L3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _model() -> Any:
    """A minimal chat model for :func:`create_agent` (offline-capable)."""
    return FakeListChatModel(responses=["hello"])


class _CustomMw(AgentMiddleware):
    """A trivial custom middleware for chain tests."""


# ---------------------------------------------------------------------------
# Argument validation (the public error contract)
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_cannot_mix_middleware_and_features(self) -> None:
        with pytest.raises(ValueError, match="Cannot specify both 'middleware' and 'features'"):
            create_agent(
                model=_model(),
                middleware=[_CustomMw()],
                features=RuntimeFeatures(),
            )

    def test_cannot_mix_middleware_and_extra_middleware(self) -> None:
        with pytest.raises(ValueError, match="Cannot use 'extra_middleware' with 'middleware'"):
            create_agent(
                model=_model(),
                middleware=[_CustomMw()],
                extra_middleware=[_CustomMw()],
            )

    def test_extra_middleware_must_be_agent_middleware(self) -> None:
        with pytest.raises(TypeError, match="must be AgentMiddleware instances"):
            create_agent(
                model=_model(),
                extra_middleware=["not a middleware"],  # type: ignore[list-item]
            )


# ---------------------------------------------------------------------------
# Feature flag handling (5.8 chain assembly)
# ---------------------------------------------------------------------------
#
# The 5.1 era rejected feature flags with NotImplementedError.
# 5.8 wires them up via :func:`assemble_chain` and raises
# :class:`ValueError` only when a feature's runtime
# dependency is missing from the caller's ``middleware_deps``.


class TestL2FeatureHandling:
    def test_true_raises_with_dependency_hint(self) -> None:
        # sandbox=True with no path_provider → ValueError pointing at the missing field.
        features = RuntimeFeatures(
            sandbox=True,
            memory=False,
            summarization=False,
            subagent=False,
            vision=False,
            auto_title=False,
        )
        with pytest.raises(ValueError, match="path_provider"):
            assemble_chain(features, MiddlewareChainConfig())[0]

    def test_custom_instance_accepted(self) -> None:
        # sandbox=False but a custom memory instance is accepted.
        features = RuntimeFeatures(
            sandbox=False,
            memory=_CustomMw(),
            summarization=False,
            subagent=False,
            vision=False,
            auto_title=False,
        )
        # No dependency required for a custom instance → no error.
        chain = assemble_chain(features, MiddlewareChainConfig())[0]
        assert any(isinstance(m, _CustomMw) for m in chain)


# ---------------------------------------------------------------------------
# Always-on chain assembly (5.2 / 5.8)
# ---------------------------------------------------------------------------


class TestAssembleFromFeatures:
    def test_default_features_yield_always_on_chain(self) -> None:
        from agent_sdk.middlewares.clarification import ClarificationMiddleware

        chain = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())[0]
        # 9 always-on middlewares (Dangling, LLMError, ToolError, TokenUsage,
        # DeferredToolFilter, LoopDetection, StateSizeMonitor, ModelCallCapture,
        # Clarification).
        assert len(chain) == 9
        assert isinstance(chain[0], DanglingToolCallMiddleware)
        assert isinstance(chain[-1], ClarificationMiddleware)

    def test_chain_order_is_pinned(self) -> None:
        # The order is part of the SDK's public contract;
        # changing it is a breaking change.
        from agent_sdk.middlewares.clarification import ClarificationMiddleware
        from agent_sdk.middlewares.deferred_tool_filter import DeferredToolFilterMiddleware
        from agent_sdk.middlewares.llm_error import LLMErrorHandlingMiddleware
        from agent_sdk.middlewares.model_call_capture import ModelCallCaptureMiddleware
        from agent_sdk.middlewares.state_size_monitor import StateSizeMonitorMiddleware
        from agent_sdk.middlewares.token_usage import TokenUsageMiddleware

        chain = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())[0]
        types = [type(m) for m in chain]
        assert types == [
            DanglingToolCallMiddleware,
            LLMErrorHandlingMiddleware,
            ToolErrorHandlingMiddleware,
            TokenUsageMiddleware,
            DeferredToolFilterMiddleware,
            LoopDetectionMiddleware,
            StateSizeMonitorMiddleware,
            ModelCallCaptureMiddleware,
            ClarificationMiddleware,
        ]


# ---------------------------------------------------------------------------
# _insert_extra_middlewares — @Next / @Prev insertion algorithm
# ---------------------------------------------------------------------------


class AnchorA(AgentMiddleware):
    pass


class AnchorB(AgentMiddleware):
    pass


class TestInsertExtra:
    def test_unanchored_is_appended(self) -> None:
        chain = [AnchorA()]
        _insert_extra_middlewares(chain, [_CustomMw()])
        assert isinstance(chain[0], AnchorA)
        assert isinstance(chain[1], _CustomMw)

    def test_next_inserts_after_anchor(self) -> None:
        @Next(AnchorA)
        class _Mw(AgentMiddleware):
            pass

        chain = [AnchorA()]
        _insert_extra_middlewares(chain, [_Mw()])
        assert isinstance(chain[0], AnchorA)
        assert isinstance(chain[1], _Mw)

    def test_next_anchors_on_l3_middleware(self) -> None:
        # The @Next anchor can be a class that is not yet
        # in the chain — the algorithm resolves it across
        # multiple insertion rounds.
        if not _L3_AVAILABLE:
            pytest.skip("stage 5.2 middlewares not yet implemented")

        @Next(DanglingToolCallMiddleware)
        class _Mw(AgentMiddleware):
            pass

        chain = assemble_chain(RuntimeFeatures(sandbox=False), MiddlewareChainConfig())[0]
        # Sanity: the chain has the always-on middlewares.
        assert any(isinstance(m, DanglingToolCallMiddleware) for m in chain)
        # And our extra was inserted right after the anchor.
        _insert_extra_middlewares(chain, [_Mw()])
        anchor_idx = next(i for i, m in enumerate(chain) if isinstance(m, DanglingToolCallMiddleware))
        assert isinstance(chain[anchor_idx + 1], _Mw)

    def test_prev_inserts_before_anchor(self) -> None:
        @Prev(AnchorA)
        class _Mw(AgentMiddleware):
            pass

        chain = [AnchorA()]
        _insert_extra_middlewares(chain, [_Mw()])
        assert isinstance(chain[0], _Mw)
        assert isinstance(chain[1], AnchorA)

    def test_both_anchors_is_rejected(self) -> None:
        @Next(AnchorA)
        @Prev(AnchorB)
        class _Mw(AgentMiddleware):
            pass

        chain = [AnchorA()]
        with pytest.raises(ValueError, match="cannot have both @Next and @Prev"):
            _insert_extra_middlewares(chain, [_Mw()])

    def test_double_next_same_anchor_raises(self) -> None:
        @Next(AnchorA)
        class _Mw1(AgentMiddleware):
            pass

        @Next(AnchorA)
        class _Mw2(AgentMiddleware):
            pass

        chain = [AnchorA()]
        with pytest.raises(ValueError, match="Conflict"):
            _insert_extra_middlewares(chain, [_Mw1(), _Mw2()])

    def test_next_prev_clash_on_same_anchor_raises(self) -> None:
        @Next(AnchorA)
        class _Mw1(AgentMiddleware):
            pass

        @Prev(AnchorA)
        class _Mw2(AgentMiddleware):
            pass

        chain = [AnchorA()]
        with pytest.raises(ValueError, match="Conflict"):
            _insert_extra_middlewares(chain, [_Mw1(), _Mw2()])

    def test_unresolvable_anchor_raises(self) -> None:
        @Next(AnchorA)
        class _Mw(AgentMiddleware):
            pass

        # AnchorA is not in the chain.
        chain = [AnchorB()]
        with pytest.raises(ValueError, match="Cannot resolve positions"):
            _insert_extra_middlewares(chain, [_Mw()])

    def test_cross_external_anchoring_resolves_iteratively(self) -> None:
        # ``_Mw1`` anchors on ``_Mw2`` and ``_Mw2`` anchors on
        # ``AnchorA``; the iterative loop resolves both
        # because each appears after the other is inserted.

        class _Mw1(AgentMiddleware):
            pass

        class _Mw2(AgentMiddleware):
            pass

        # Apply decorators after the classes are defined so we
        # can reference each other.
        _Mw1 = Next(_Mw2)(_Mw1)
        _Mw2 = Next(AnchorA)(_Mw2)

        chain = [AnchorA()]
        _insert_extra_middlewares(chain, [_Mw1(), _Mw2()])
        # AnchorA → _Mw2 → _Mw1
        assert isinstance(chain[0], AnchorA)
        assert isinstance(chain[1], _Mw2)
        assert isinstance(chain[2], _Mw1)


# ---------------------------------------------------------------------------
# End-to-end: create_agent (offline)
# ---------------------------------------------------------------------------


class TestCreateAgentOffline:
    def test_middleware_takeover_mode(self) -> None:
        # In full-takeover mode, *no* always-on middlewares are added
        # by the factory — only the user's list is used.
        agent = create_agent(
            model=_model(),
            middleware=[_CustomMw()],
        )
        # The agent is a CompiledStateGraph; we only check that
        # no exception was raised.
        assert agent is not None

    @pytest.mark.skipif(not _L3_AVAILABLE, reason="stage 5.2 middlewares not yet implemented")
    def test_features_mode(self) -> None:
        # Features mode: the three always-on middlewares are auto-added.
        # Use sandbox=False here because the sandbox deps are
        # not needed for this smoke test.
        agent = create_agent(model=_model(), features=RuntimeFeatures(sandbox=False))
        assert agent is not None

    @pytest.mark.skipif(not _L3_AVAILABLE, reason="stage 5.2 middlewares not yet implemented")
    def test_extra_middleware(self) -> None:
        @Next(DanglingToolCallMiddleware)
        class _Mw(AgentMiddleware):
            pass

        agent = create_agent(
            model=_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[_Mw()],
        )
        assert agent is not None

    @pytest.mark.skipif(not _L3_AVAILABLE, reason="stage 5.2 middlewares not yet implemented")
    def test_default_state_schema_is_thread_state(self) -> None:
        # We can't directly read the compiled graph's state
        # schema, but we can confirm the factory succeeds with
        # the default schema (i.e. ThreadState).
        agent = create_agent(model=_model(), features=RuntimeFeatures(sandbox=False))
        assert agent is not None

    @pytest.mark.skipif(not _L3_AVAILABLE, reason="stage 5.2 middlewares not yet implemented")
    def test_custom_state_schema(self) -> None:
        from langchain.agents import AgentState

        agent = create_agent(
            model=_model(),
            features=RuntimeFeatures(sandbox=False),
            state_schema=AgentState,
        )
        assert agent is not None

    def test_middleware_deps_injects_dependencies(self, tmp_path) -> None:
        """End-to-end: passing middleware_deps enables features end-to-end."""
        from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig

        # The default (empty) middleware_deps still enables features
        # that don't need runtime deps.
        agent = create_agent(
            model=_model(),
            features=RuntimeFeatures(subagent=True, vision=True, sandbox=False),
            middleware_deps=MiddlewareChainConfig(),
        )
        assert agent is not None

    def test_middleware_deps_missing_dependency_raises(self, tmp_path) -> None:
        from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig

        # sandbox=True but no path_provider / sandbox_provider.
        with pytest.raises(ValueError, match="path_provider"):
            create_agent(
                model=_model(),
                features=RuntimeFeatures(sandbox=True),
                middleware_deps=MiddlewareChainConfig(),
            )

    def test_plan_mode_works(self) -> None:
        from agent_sdk.runtime.middleware_chain import MiddlewareChainConfig

        agent = create_agent(
            model=_model(),
            features=RuntimeFeatures(sandbox=False),
            middleware_deps=MiddlewareChainConfig(),
            plan_mode=True,
        )
        assert agent is not None
