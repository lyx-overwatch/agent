"""DeerFlow preset: AuditRules preserving the original command audit policy.

:class:`DeerFlowAuditRules` re-records (per ADR-010) the
high-risk and medium-risk command patterns that the original
``backend.agents.middlewares.sandbox_audit_middleware`` ships
with. The set covers:

* destructive filesystem operations (``rm -rf /``,
  ``dd if=…``, ``mkfs``, overwriting system files);
* writing into the system binary tree, shell startup files,
  or the ``/etc`` tree;
* dynamic-linker hijack (``LD_PRELOAD`` / ``LD_LIBRARY_PATH``);
* unquoted pipes to a shell (``| bash``);
* command-substitution of dangerous binaries (curl, wget,
  python, …);
* base64 decode piped onward;
* process-environment leakage;
* ``/dev/tcp/`` networking (bypasses tool allowlists);
* fork-bomb style constructions;
* chmod 777 / pip / apt install / sudo / PATH mutation as
  medium-risk (warn but allow).

Notes (per ADR-010 re-implementation):
    * The patterns are re-typed in this module rather than
      imported from ``backend.*`` or copied from
      ``backend/agents/middlewares/sandbox_audit_middleware.py``.
    * The classification algorithm itself lives in
      :mod:`agent_sdk.sandbox.audit.middleware`; this module
      only contributes the rule set.
    * The classification algorithm behaviour is verified to be
      equivalent by running the SDK middleware on the same
      golden fixture commands the backend uses in its own test
      suite.
"""

from __future__ import annotations

import re

from agent_sdk.sandbox.audit.rules import AuditPattern

# High-risk patterns: a single match blocks the command outright.
# These are all the structural attacks that the original backend
# rule set was designed to catch, re-typed here from scratch.
_HIGH_RISK: list[AuditPattern] = [
    AuditPattern(
        re.compile(r"rm\s+-[^\s]*r[^\s]*\s+(/\*?|~/?\*?|/(home|root)\b)\s*$"),
        "high",
        "rm -r on a root / home / user directory",
    ),
    AuditPattern(
        re.compile(r"dd\s+if="),
        "high",
        "dd disk operation (raw block device write)",
    ),
    AuditPattern(
        re.compile(r"\bmkfs(\.|\s|$)"),
        "high",
        "mkfs filesystem creation (formats a device)",
    ),
    AuditPattern(
        re.compile(r"cat\s+/etc/shadow"),
        "high",
        "reading /etc/shadow (credential exposure)",
    ),
    AuditPattern(
        re.compile(r">+\s*/etc/"),
        "high",
        "writing into /etc (system configuration mutation)",
    ),
    AuditPattern(
        re.compile(r"\|\s*(ba)?sh\b"),
        "high",
        "piping remote content into a shell",
    ),
    AuditPattern(
        re.compile(r"[`$]\(?\s*(curl|wget|bash|sh|python|ruby|perl|base64)\b"),
        "high",
        "command substitution of a dangerous executable",
    ),
    AuditPattern(
        re.compile(r"base64\s+.*-d.*\|"),
        "high",
        "base64 decode piped to another command",
    ),
    AuditPattern(
        re.compile(r">+\s*(/usr/bin/|/bin/|/sbin/)"),
        "high",
        "overwriting a system binary",
    ),
    AuditPattern(
        re.compile(r">+\s*~/?\.(bashrc|profile|zshrc|bash_profile)"),
        "high",
        "overwriting a shell startup file",
    ),
    AuditPattern(
        re.compile(r"/proc/[^/]+/environ"),
        "high",
        "process environment leak via /proc",
    ),
    AuditPattern(
        re.compile(r"\b(LD_PRELOAD|LD_LIBRARY_PATH)\s*="),
        "high",
        "dynamic linker hijack",
    ),
    AuditPattern(
        re.compile(r"/dev/tcp/"),
        "high",
        "bash built-in networking (bypasses tool allowlists)",
    ),
    AuditPattern(
        # classic fork bomb shape: name(){ body| name & };
        re.compile(r"\S+\(\)\s*\{[^}]*\|\s*\S+\s*&"),
        "high",
        "fork bomb (name(){ ... | name & })",
    ),
    AuditPattern(
        re.compile(r"while\s+true.*&\s*done"),
        "high",
        "fork-bomb variant (while true; do ... & done)",
    ),
]


# Medium-risk patterns: a match warns the LLM but does not block.
_MEDIUM_RISK: list[AuditPattern] = [
    AuditPattern(
        re.compile(r"\bchmod\s+777\b"),
        "medium",
        "world-writable permissions",
    ),
    AuditPattern(
        re.compile(r"\bpip3?\s+install\b"),
        "medium",
        "pip install (mutates the runtime environment)",
    ),
    AuditPattern(
        re.compile(r"\bapt(-get)?\s+install\b"),
        "medium",
        "apt install (mutates the runtime environment)",
    ),
    AuditPattern(
        re.compile(r"\b(sudo|su)\b"),
        "medium",
        "sudo / su (no-op under Docker root, but worth noting)",
    ),
    AuditPattern(
        re.compile(r"\bPATH\s*="),
        "medium",
        "PATH mutation (long attack chain)",
    ),
]


class DeerFlowAuditRules:
    """DeerFlow's default command audit policy.

    The set of patterns re-records the original backend's
    high-risk and medium-risk rules. The classification
    algorithm (compound splitting, shlex fallback, fail-closed
    on unclosed quotes) lives in
    :class:`agent_sdk.sandbox.audit.SandboxAuditMiddleware`.
    """

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        return list(_HIGH_RISK)

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        return list(_MEDIUM_RISK)

    def get_low_risk_patterns(self) -> list[AuditPattern]:
        # The original backend has no low-risk rules. Returning an
        # empty list keeps the runtime's audit log noise-free.
        return []
