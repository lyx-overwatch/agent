"""Audit subsystem for sandbox command execution.

This subpackage provides the brand-neutral injection point for
shell command security auditing. Consumers obtain an
:class:`AuditRules` instance (default: no rules) and pass it to
:class:`SandboxAuditMiddleware`. The middleware then runs every
``bash`` tool call through the rule set, classifying the command
as :data:`AuditVerdict.BLOCK`, :data:`AuditVerdict.WARN`, or
:data:`AuditVerdict.PASS`.

The default implementation is empty
(:class:`DefaultAuditRules`); the DeerFlow preset supplies a
comprehensive rule set
(:class:`agent_sdk.presets.deerflow.DeerFlowAuditRules`).
"""

from __future__ import annotations

from agent_sdk.sandbox.audit.default import DefaultAuditRules
from agent_sdk.sandbox.audit.middleware import SandboxAuditMiddleware
from agent_sdk.sandbox.audit.rules import AuditPattern, AuditRules, AuditVerdict

__all__ = [
    "AuditPattern",
    "AuditRules",
    "AuditVerdict",
    "DefaultAuditRules",
    "SandboxAuditMiddleware",
]
