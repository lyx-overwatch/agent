"""AuditRules Protocol — the brand-neutral injection point for command auditing.

This module defines the *shape* of a security audit policy. The
runtime does not bake any specific commands into the SDK; instead
it consults an :class:`AuditRules` instance at classification time
and defers all pattern definitions to that instance.

Why a Protocol and not a concrete base class?
    * Different products have radically different threat models.
      A Protocol keeps the SDK from dictating what counts as
      "high risk" — it merely provides a slot to plug a policy in.
    * Tests can construct a 3-line Protocol implementation in
      place without subclassing.

Risk levels
    * **high** → middleware **blocks** the command outright
    * **medium** → middleware **runs** the command and appends a
      warning to the tool result
    * **low** → middleware logs the command only

The Protocol surface is intentionally minimal: three getters, one
per risk level. The :class:`AuditPattern` value object carries the
compiled regex, a free-form description (for the warning text) and
the risk level it belongs to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class AuditVerdict(str, Enum):
    """Classification of a command by :class:`SandboxAuditMiddleware`.

    The string values are also the wire format the middleware
    emits to the audit log, so logging is stable across
    re-implementations.
    """

    BLOCK = "block"
    WARN = "warn"
    PASS = "pass"


@dataclass(frozen=True)
class AuditPattern:
    """A single security audit pattern.

    Attributes:
        pattern: A compiled regex. The middleware uses
            :func:`re.Pattern.search` so partial matches count.
        risk_level: One of ``"high"``, ``"medium"``, ``"low"``.
        description: Human-readable explanation. The middleware
            surfaces this text to the LLM as a warning (medium)
            or block reason (high).
    """

    pattern: re.Pattern[str]
    risk_level: str
    description: str

    def __post_init__(self) -> None:
        if self.risk_level not in {"high", "medium", "low"}:
            raise ValueError(
                f"Invalid risk_level {self.risk_level!r}; "
                "expected 'high', 'medium', or 'low'."
            )


@runtime_checkable
class AuditRules(Protocol):
    """Brand-neutral shell command audit policy.

    Implementations expose three getters, one per risk level. The
    middleware consults them in order — high first, then medium,
    then low — and short-circuits on the first match.
    """

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        """Return patterns that should BLOCK command execution.

        A ``high`` match stops the tool handler from being called
        and returns an error ``ToolMessage`` to the agent loop.
        """
        ...

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        """Return patterns that should WARN but allow execution.

        A ``medium`` match lets the handler run, then appends a
        warning to the tool result so the LLM is aware.
        """
        ...

    def get_low_risk_patterns(self) -> list[AuditPattern]:
        """Return patterns that should be LOGGED but not warned.

        A ``low`` match is recorded in the audit log but has no
        effect on the command's execution. Implementations may
        return an empty list if they do not care to log such
        commands.
        """
        ...
