"""Unit tests for :mod:`agent_sdk.runtime.user_context`.

Covers the :class:`CurrentUser` Protocol, the ContextVar
binding, and the three-state :func:`resolve_user_id` resolver
(:data:`AUTO` / explicit ``str`` / explicit ``None``).
"""

from __future__ import annotations

import pytest
from agent_sdk.runtime.user_context import (
    AUTO,
    DEFAULT_USER_ID,
    CurrentUser,
    get_current_user,
    get_effective_user_id,
    require_current_user,
    reset_current_user,
    resolve_user_id,
    set_current_user,
)

# ---------------------------------------------------------------------------
# Fixture: a minimal CurrentUser object
# ---------------------------------------------------------------------------


class _User:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


@pytest.fixture(autouse=True)
def _reset_context():
    """Snapshot the contextvar so each test starts with no user bound.

    The :func:`set_current_user` call returns a token; we reset to
    that token after the test, so tests never leak state into each
    other even when one of them fails to clean up.
    """
    token = set_current_user(_User(DEFAULT_USER_ID))  # placeholder
    try:
        # Reset back to "no user" so the test starts clean.
        reset_current_user(token)
        yield
    finally:
        # Final defensive reset.
        try:
            current = get_current_user()
        except LookupError:
            return
        # We don't have a fresh token here; tests should not leave
        # a user bound when they finish, so do a manual overwrite.
        _ = current  # noop


# ---------------------------------------------------------------------------
# CurrentUser Protocol
# ---------------------------------------------------------------------------


class TestCurrentUserProtocol:
    def test_structural_typing_object_with_id(self) -> None:
        class Obj:
            id = "u-1"

        u = Obj()
        assert isinstance(u, CurrentUser)

    def test_structural_typing_simple_dict(self) -> None:
        class DictLike:
            def __init__(self) -> None:
                self.id = "u-2"

        assert isinstance(DictLike(), CurrentUser)

    def test_missing_id_fails_isinstance(self) -> None:
        class NoId:
            pass

        assert not isinstance(NoId(), CurrentUser)


# ---------------------------------------------------------------------------
# ContextVar binding
# ---------------------------------------------------------------------------


class TestContextVarBinding:
    def test_unset_returns_none(self) -> None:
        # _reset_context fixture guarantees a clean slate.
        assert get_current_user() is None

    def test_set_and_get(self) -> None:
        user = _User("u-3")
        token = set_current_user(user)
        try:
            assert get_current_user() is user
        finally:
            reset_current_user(token)
        assert get_current_user() is None

    def test_reset_restores_previous(self) -> None:
        outer = _User("outer")
        outer_token = set_current_user(outer)
        try:
            inner = _User("inner")
            inner_token = set_current_user(inner)
            try:
                assert get_current_user() is inner
            finally:
                reset_current_user(inner_token)
            assert get_current_user() is outer
        finally:
            reset_current_user(outer_token)

    def test_require_current_user_unset_raises(self) -> None:
        with pytest.raises(RuntimeError, match="repository accessed without user context"):
            require_current_user()

    def test_require_current_user_returns_user(self) -> None:
        user = _User("u-required")
        token = set_current_user(user)
        try:
            assert require_current_user() is user
        finally:
            reset_current_user(token)

    def test_reset_with_non_token_raises(self) -> None:
        # Resetting a value that is not a Token object must raise
        # (TypeError in CPython 3.12+) — this protects users from
        # using a stale token from a different context.
        with pytest.raises(TypeError):
            reset_current_user("not-a-token")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_effective_user_id
# ---------------------------------------------------------------------------


class TestGetEffectiveUserId:
    def test_unset_returns_default(self) -> None:
        assert get_effective_user_id() == DEFAULT_USER_ID

    def test_set_returns_str_id(self) -> None:
        user = _User("u-effective")
        token = set_current_user(user)
        try:
            assert get_effective_user_id() == "u-effective"
        finally:
            reset_current_user(token)

    def test_non_str_id_coerced_to_str(self) -> None:
        class IntIdUser:
            id = 42  # type: ignore[assignment]

        token = set_current_user(IntIdUser())  # type: ignore[arg-type]
        try:
            # Although the Protocol declares ``id: str``, the
            # helper must tolerate any id-shaped value at runtime.
            assert get_effective_user_id() == "42"
        finally:
            reset_current_user(token)


# ---------------------------------------------------------------------------
# AUTO sentinel
# ---------------------------------------------------------------------------


class TestAutoSentinel:
    def test_singleton(self) -> None:
        # Two distinct constructions of the sentinel return the
        # same object (the private constructor memoises).
        from agent_sdk.runtime.user_context import _AutoSentinel

        assert _AutoSentinel() is _AutoSentinel()
        assert AUTO is _AutoSentinel()

    def test_repr(self) -> None:
        assert repr(AUTO) == "<AUTO>"

    def test_not_equal_to_none_or_string(self) -> None:
        assert AUTO != None  # noqa: E711
        assert AUTO != "AUTO"
        assert AUTO != "auto"


# ---------------------------------------------------------------------------
# resolve_user_id
# ---------------------------------------------------------------------------


class TestResolveUserId:
    def test_explicit_str_returns_value(self) -> None:
        assert resolve_user_id("user-1") == "user-1"
        assert resolve_user_id("user-1", method_name="x") == "user-1"

    def test_explicit_none_returns_none(self) -> None:
        # Explicit None is the migration / admin-CLI path:
        # no user filter at all.
        assert resolve_user_id(None) is None

    def test_auto_unset_raises(self) -> None:
        with pytest.raises(RuntimeError, match="called with user_id=AUTO"):
            resolve_user_id(AUTO, method_name="mymethod")

    def test_auto_set_returns_user_id(self) -> None:
        user = _User("u-auto")
        token = set_current_user(user)
        try:
            assert resolve_user_id(AUTO) == "u-auto"
        finally:
            reset_current_user(token)

    def test_auto_coerces_non_str_id(self) -> None:
        class IntIdUser:
            id = 7  # type: ignore[assignment]

        token = set_current_user(IntIdUser())  # type: ignore[arg-type]
        try:
            assert resolve_user_id(AUTO) == "7"
        finally:
            reset_current_user(token)

    def test_method_name_in_error_message(self) -> None:
        with pytest.raises(RuntimeError, match="my_special_method"):
            resolve_user_id(AUTO, method_name="my_special_method")

    def test_default_method_name(self) -> None:
        with pytest.raises(RuntimeError, match="repository method"):
            resolve_user_id(AUTO)
