"""@Next / @Prev — middleware chain positioning decorators.

These two class decorators let a middleware declare *where* it
wants to live in the assembled chain without coupling to the
factory function. They are pure metadata: the decorator only
sets a class attribute (``_next_anchor`` / ``_prev_anchor``)
that :func:`create_agent`'s chain assembler reads at the end of
``extra_middleware`` insertion.

Why class attributes and not a separate registry?
    * Class attributes travel with the class — the user can
      import the middleware and see its position in the IDE.
    * Multiple ``extra_middleware`` calls from different
      callers compose without a shared mutable structure.
    * It matches the original ``deerflow.agents.features`` API
      so the ``DeerFlowAgent`` preset can reuse these
      decorators verbatim.

Example:

    from langchain.agents.middleware import AgentMiddleware
    from agent_sdk.runtime import Next, Prev

    @Next(LoopDetectionMiddleware)
    class MyWatchdogMiddleware(AgentMiddleware):
        ...

    @Prev(ClarificationMiddleware)
    class MyPreClarificationMiddleware(AgentMiddleware):
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware


def _validate_anchor(anchor: object) -> type[AgentMiddleware]:
    """Return *anchor* if it is an :class:`AgentMiddleware` subclass, else raise ``TypeError``."""
    from langchain.agents.middleware import AgentMiddleware  # local import: avoid runtime cost when only types are needed

    if not (isinstance(anchor, type) and issubclass(anchor, AgentMiddleware)):
        raise TypeError(
            f"@Next / @Prev expects an AgentMiddleware subclass, got {anchor!r}. "
            "Pass the class itself (e.g. @Next(MyMiddleware)), not an instance."
        )
    return anchor


def Next(anchor: type[AgentMiddleware]):
    """Declare this middleware should be placed *after* *anchor* in the chain.

    The decorator only sets ``cls._next_anchor = anchor``. The
    chain assembler in :func:`create_agent` reads the attribute
    when inserting ``extra_middleware``.

    A middleware MAY NOT carry both ``@Next`` and ``@Prev`` —
    the assembler will raise ``ValueError`` if it encounters
    such a class.
    """
    validated = _validate_anchor(anchor)

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        cls._next_anchor = validated  # type: ignore[attr-defined]
        return cls

    return decorator


def Prev(anchor: type[AgentMiddleware]):
    """Declare this middleware should be placed *before* *anchor* in the chain.

    Mirrors :func:`Next` but sets ``cls._prev_anchor``. See
    :func:`Next` for the rationale on class attributes and the
    "not both @Next and @Prev" rule.
    """
    validated = _validate_anchor(anchor)

    def decorator(cls: type[AgentMiddleware]) -> type[AgentMiddleware]:
        cls._prev_anchor = validated  # type: ignore[attr-defined]
        return cls

    return decorator
