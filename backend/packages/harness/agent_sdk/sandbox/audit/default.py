"""Default AuditRules — an empty policy.

:class:`DefaultAuditRules` is the SDK's reference implementation
of :class:`AuditRules` when no project-specific policy is
needed. Every command passes the audit; the audit log is silent.

A fresh project adopting the SDK can use this as-is, or subclass
it to add patterns. The DeerFlow preset replaces it with
:class:`agent_sdk.presets.deerflow.DeerFlowAuditRules`, which
supplies a comprehensive rule set that mirrors the behaviour of
the original ``backend.agents.middlewares.sandbox_audit_middleware``
module.
"""

from __future__ import annotations

from agent_sdk.sandbox.audit.rules import AuditPattern


class DefaultAuditRules:
    """An empty :class:`AuditRules` — every command passes."""

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        return []

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        return []

    def get_low_risk_patterns(self) -> list[AuditPattern]:
        return []
