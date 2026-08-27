"""Request-scoped user context for user-based authorization.

This module holds a :class:`~contextvars.ContextVar` that the
gateway's auth middleware (or any other producer) sets after a
successful authentication. Repository methods and middleware
read the contextvar via a :class:`CurrentUser` Protocol, so that
business code stays free of ``user_id`` boilerplate.

Three-state semantics for the ``user_id`` parameter at
repository / middleware boundaries (mirrors the in-tree
reference, but brand-neutral and free of any backend import):

* :data:`AUTO` (default): read from contextvar; raise
  :class:`RuntimeError` if unset.
* Explicit ``str``: use the provided value, overriding any
  contextvar value.
* Explicit ``None``: no ``WHERE`` clause — used only by
  migration scripts and admin CLIs that intentionally bypass
  isolation.

Dependency direction
--------------------
Lower-layer modules (memory storage, sandbox bookkeeping, file
operations) read from this module; higher-layer modules
(auth middleware, gateway routers) write to it. ``CurrentUser``
is defined here as a :class:`typing.Protocol` so that
lower-layer code never needs to import any concrete
``User`` class from a higher layer — any object with an
``.id: str`` attribute structurally satisfies the protocol.

Asyncio semantics
-----------------
``ContextVar`` is task-local under asyncio, not thread-local.
Each request running in its own asyncio task therefore sees a
naturally isolated context. ``asyncio.create_task`` and
``asyncio.to_thread`` inherit the parent task's context, which
is typically the intended behaviour; if a background task must
*not* see the foreground user, wrap it with
``contextvars.copy_context()`` to obtain a clean copy.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    """Structural type for the current authenticated user.

    Any object with an ``.id: str`` attribute satisfies this
    protocol. Concrete implementations live in user code
    (e.g. a FastAPI dependency that decodes a JWT, or a
    CLI wrapper that reads ``--user``).
    """

    id: str


#: Context variable holding the current user, or ``None`` when
#: no user has been bound to the running task.
_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar(
    "agent_sdk_current_user",
    default=None,
)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Bind *user* as the current user for this async task.

    Returns a reset token that **must** be passed to
    :func:`reset_current_user` in a ``finally`` block to
    restore the previous context. Failing to reset the token
    leaks the user identity into subsequent unrelated tasks
    scheduled on the same task slot.

    Example:
        >>> token = set_current_user(user)
        >>> try:
        ...     handle_request()
        ... finally:
        ...     reset_current_user(token)
    """
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the context to the state captured by *token*."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or ``None`` if unset.

    Safe to call in any context. Used by code paths that can
    proceed without a user (e.g. migration scripts, public
    endpoints, top-level CLI commands that have no auth
    layer).
    """
    return _current_user.get()


def require_current_user() -> CurrentUser:
    """Return the current user, or raise :class:`RuntimeError`.

    Used by repository code that must not be called outside a
    request-authenticated context. The error message is
    phrased so that a caller debugging a stack trace can locate
    the offending code path.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

#: Fallback user id when no user is bound to the running task.
#: Used for filesystem-path resolution where a valid user bucket
#: is always needed; business code that needs strict isolation
#: should call :func:`require_current_user` instead.
DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the current user's id as a string.

    Unlike :func:`require_current_user` this never raises — it
    is designed for filesystem-path resolution where a valid
    user bucket is always needed. When the contextvar is unset
    (e.g. an unauthenticated request, a background maintenance
    job), it falls back to :data:`DEFAULT_USER_ID`.

    The id is coerced to ``str`` at the boundary: callers are
    free to use any id-shaped type (``UUID``, ``int``, etc.)
    and the SDK guarantees a string for filesystem use.
    """
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument
# that defaults to :data:`AUTO`. The three possible values drive
# distinct behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    """Singleton marker meaning "resolve user_id from contextvar"."""

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<AUTO>"


#: Singleton sentinel meaning "read user_id from the contextvar".
#: The default for repository-style keyword arguments.
AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    """Resolve a ``user_id`` parameter to a concrete value.

    Three-state semantics:

    * :data:`AUTO` (default): read from the contextvar; raise
      :class:`RuntimeError` if no user is in context. This is
      the common case for request-scoped calls.
    * Explicit ``str``: use the provided id verbatim, overriding
      any contextvar value. Useful for tests and admin-override
      flows.
    * Explicit ``None``: no filter — the repository should skip
      the ``user_id WHERE`` clause entirely. Reserved for
      migration scripts and CLI tools that intentionally bypass
      isolation.

    Args:
        value: One of the three states described above.
        method_name: Name of the calling method, used to build a
            helpful error message when :data:`AUTO` is used
            outside an authenticated context.

    Returns:
        The resolved user id (``str``), or ``None`` when the
        caller explicitly opted out of user filtering.
    """
    if isinstance(value, _AutoSentinel):
        user = _current_user.get()
        if user is None:
            raise RuntimeError(
                f"{method_name} called with user_id=AUTO but no user context is set; "
                "pass an explicit user_id, set the contextvar via auth middleware, "
                "or opt out with user_id=None for migration/CLI paths."
            )
        # Coerce to ``str`` at the boundary: ``User.id`` may be a
        # richer type (``UUID`` etc.) in some applications, but
        # the SDK's filesystem layer only accepts strings.
        return str(user.id)
    return value
