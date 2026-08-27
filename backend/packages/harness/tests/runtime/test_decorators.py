"""Unit tests for the :func:`Next` and :func:`Prev` decorators."""

from __future__ import annotations

import pytest
from agent_sdk.runtime import Next, Prev
from langchain.agents.middleware import AgentMiddleware


class Anchor(AgentMiddleware):
    """A trivial :class:`AgentMiddleware` used as the @Next/@Prev anchor."""


class TestNext:
    def test_sets_next_anchor(self) -> None:
        @Next(Anchor)
        class _Mw(AgentMiddleware):
            pass

        assert _Mw._next_anchor is Anchor

    def test_returns_class_unchanged(self) -> None:
        @Next(Anchor)
        class _Mw(AgentMiddleware):
            pass

        # Decorator must return the class itself (identity), so
        # downstream isinstance checks keep working.
        assert _Mw.__name__ == "_Mw"


class TestPrev:
    def test_sets_prev_anchor(self) -> None:
        @Prev(Anchor)
        class _Mw(AgentMiddleware):
            pass

        assert _Mw._prev_anchor is Anchor


class TestDecoratorValidation:
    def test_next_rejects_instance(self) -> None:
        with pytest.raises(TypeError, match="AgentMiddleware subclass"):

            @Next(Anchor())  # type: ignore[arg-type]
            class _Mw(AgentMiddleware):
                pass

    def test_next_rejects_non_class(self) -> None:
        with pytest.raises(TypeError, match="AgentMiddleware subclass"):

            @Next(42)  # type: ignore[arg-type]
            class _Mw(AgentMiddleware):
                pass

    def test_prev_rejects_instance(self) -> None:
        with pytest.raises(TypeError, match="AgentMiddleware subclass"):

            @Prev(Anchor())  # type: ignore[arg-type]
            class _Mw(AgentMiddleware):
                pass

    def test_next_rejects_non_agentmiddleware_subclass(self) -> None:
        class NotAMiddleware:
            pass

        with pytest.raises(TypeError, match="AgentMiddleware subclass"):

            @Next(NotAMiddleware)  # type: ignore[arg-type]
            class _Mw(AgentMiddleware):
                pass
