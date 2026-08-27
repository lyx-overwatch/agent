"""SandboxAuditMiddleware — command-execution security audit, brand-neutral.

This is the SDK's re-implementation (per ADR-010) of the audit
machinery that originally lived in
``backend.agents.middlewares.sandbox_audit_middleware``. The
behaviour is preserved:

* every ``bash`` tool call is classified as
  :data:`AuditVerdict.BLOCK`, :data:`AuditVerdict.WARN`, or
  :data:`AuditVerdict.PASS`;
* compound commands (joined by ``;``/``&&``/``||``) are split
  and classified per sub-command, but the *whole* command is
  also scanned against the high-risk list so that multi-statement
  attacks like ``:(){ :|:& };:`` are still caught;
* high-risk commands are blocked with an error ``ToolMessage``;
* medium-risk commands run normally but have a warning appended
  to the tool result;
* every call is recorded in the audit log.

The brand-specific bit — the actual regex rules — is injected
via the :class:`AuditRules` Protocol. The default is
:class:`DefaultAuditRules` (no rules); the DeerFlow preset
supplies :class:`agent_sdk.presets.deerflow.DeerFlowAuditRules`.

Construction:

    SandboxAuditMiddleware()                    # → DefaultAuditRules
    SandboxAuditMiddleware(audit_rules=MyImpl) # → MyImpl
"""

from __future__ import annotations

import json
import logging
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from agent_sdk.sandbox.audit.default import DefaultAuditRules
from agent_sdk.sandbox.audit.rules import AuditPattern, AuditRules, AuditVerdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command classification helpers (brand-neutral)
# ---------------------------------------------------------------------------


def _split_compound_command(command: str) -> list[str]:
    """Split a compound command into sub-commands (quote-aware).

    Mirrors the behaviour of the original backend helper:
    unquoted ``&&`` / ``||`` / ``;`` are recognised even when
    not surrounded by whitespace, and operators inside quotes
    are ignored. If the command ends with an unclosed quote or
    a dangling escape, the whole command is returned unchanged
    (fail-closed).
    """
    parts: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    escaping = False
    index = 0

    while index < len(command):
        char = command[index]

        if escaping:
            current.append(char)
            escaping = False
            index += 1
            continue

        if char == "\\" and not in_single_quote:
            current.append(char)
            escaping = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            if command.startswith("&&", index) or command.startswith("||", index):
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += 2
                continue
            if char == ";":
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                index += 1
                continue

        current.append(char)
        index += 1

    # Unclosed quote or dangling escape → fail-closed.
    if in_single_quote or in_double_quote or escaping:
        return [command]

    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts if parts else [command]


def _match_any(patterns: list[AuditPattern], text: str) -> AuditPattern | None:
    """Return the first pattern that matches *text*, or ``None``."""
    for pattern in patterns:
        if pattern.pattern.search(text):
            return pattern
    return None


def _classify_single_command(command: str, high: list[AuditPattern], medium: list[AuditPattern]) -> tuple[AuditVerdict, AuditPattern | None]:
    """Classify a single (non-compound) command.

    Returns ``(verdict, matched_pattern)``. The matched pattern
    is non-``None`` only for ``BLOCK`` and ``WARN`` verdicts —
    callers need the description to surface to the LLM.
    """
    normalized = " ".join(command.split())

    matched = _match_any(high, normalized)
    if matched is not None:
        return AuditVerdict.BLOCK, matched

    # Also try shlex-parsed tokens: catches cases like an
    # injection that the raw-string scan missed.
    try:
        tokens = shlex.split(command)
        joined = " ".join(tokens)
        matched = _match_any(high, joined)
        if matched is not None:
            return AuditVerdict.BLOCK, matched
    except ValueError:
        # shlex.split fails on unclosed quotes — treat as suspicious.
        return AuditVerdict.BLOCK, None

    matched = _match_any(medium, normalized)
    if matched is not None:
        return AuditVerdict.WARN, matched

    return AuditVerdict.PASS, None


def _classify_command(command: str, high: list[AuditPattern], medium: list[AuditPattern]) -> tuple[AuditVerdict, AuditPattern | None]:
    """Classify a command that may be compound.

    Returns ``(verdict, matched_pattern)``.

    Strategy (preserved from the original backend implementation):

    1. Scan the *whole* raw command against high-risk patterns.
       This catches structural attacks like ``while true; do
       bash & done`` that span multiple shell statements.
    2. Split compound commands on ``;``/``&&``/``||`` and
       classify each sub-command independently. The most
       severe verdict wins.
    """
    # Pass 1: whole-command high-risk scan.
    normalized = " ".join(command.split())
    matched = _match_any(high, normalized)
    if matched is not None:
        return AuditVerdict.BLOCK, matched

    # Pass 2: per-sub-command classification.
    sub_commands = _split_compound_command(command)
    worst: AuditVerdict = AuditVerdict.PASS
    worst_pattern: AuditPattern | None = None
    for sub in sub_commands:
        verdict, pattern = _classify_single_command(sub, high, medium)
        if verdict == AuditVerdict.BLOCK:
            return AuditVerdict.BLOCK, pattern  # short-circuit
        if verdict == AuditVerdict.WARN:
            worst = AuditVerdict.WARN
            worst_pattern = pattern
    return worst, worst_pattern


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class _SandboxAuditState(AgentState):
    """State schema for the audit middleware.

    Defined locally so the SDK doesn't import ``deerflow.agents.thread_state``.
    The fields below are what the audit middleware actually reads or
    writes — nothing else.
    """

    # Audit log is injected under a well-known key for downstream tools.
    audit_log: list[dict[str, Any]] | None


class SandboxAuditMiddleware(AgentMiddleware[_SandboxAuditState]):
    """Audit shell commands against an :class:`AuditRules` policy.

    The middleware only inspects calls to the ``bash`` tool; any
    other tool name is passed straight through.

    Args:
        audit_rules: The :class:`AuditRules` instance to consult.
            ``None`` (the default) uses :class:`DefaultAuditRules`
            which permits every command.
        tool_name: The tool name to audit. Defaults to ``"bash"``,
            matching the canonical DeerFlow name. Override this
            if your project renames the tool.
    """

    state_schema = _SandboxAuditState

    # Normal bash commands rarely exceed a few hundred characters;
    # 10 000 is well above any legitimate use case yet a tiny
    # fraction of Linux ARG_MAX. Anything longer is almost
    # certainly a payload injection or base64-encoded attack.
    _MAX_COMMAND_LENGTH = 10_000

    # Audit log truncation threshold. The log entry keeps the
    # full command under this many characters, otherwise it
    # records a head-only preview.
    _AUDIT_COMMAND_LIMIT = 200

    def __init__(
        self,
        audit_rules: AuditRules | None = None,
        tool_name: str = "bash",
    ) -> None:
        super().__init__()
        self._rules: AuditRules = audit_rules or DefaultAuditRules()
        self._tool_name = tool_name

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_thread_id(self, request: ToolCallRequest) -> str | None:
        runtime = request.runtime  # ToolRuntime; may be None-like in tests
        if runtime is None:
            return None
        ctx = getattr(runtime, "context", None) or {}
        thread_id = ctx.get("thread_id") if isinstance(ctx, dict) else None
        if thread_id is None:
            cfg = getattr(runtime, "config", None) or {}
            thread_id = cfg.get("configurable", {}).get("thread_id")
        return thread_id

    def _write_audit(self, thread_id: str | None, command: str, verdict: AuditVerdict, *, truncate: bool = False) -> None:
        audited_command = command
        if truncate and len(command) > self._AUDIT_COMMAND_LIMIT:
            audited_command = f"{command[: self._AUDIT_COMMAND_LIMIT]}... ({len(command)} chars)"
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "thread_id": thread_id or "unknown",
            "command": audited_command,
            "verdict": verdict.value,
        }
        logger.info("[SandboxAudit] %s", json.dumps(record, ensure_ascii=False))

    def _build_block_message(self, request: ToolCallRequest, reason: str) -> ToolMessage:
        tool_call_id = str(request.tool_call.get("id") or "missing_id")
        return ToolMessage(
            content=f"Command blocked: {reason}. Please use a safer alternative approach.",
            tool_call_id=tool_call_id,
            name=self._tool_name,
            status="error",
        )

    def _append_warn_to_result(self, result: ToolMessage | Command, command: str) -> ToolMessage | Command:
        """Append a warning note to the tool result for medium-risk commands."""
        if not isinstance(result, ToolMessage):
            return result
        warning = f"\n\n⚠️ Warning: `{command}` is a medium-risk command that may modify the runtime environment."
        if isinstance(result.content, list):
            new_content = list(result.content) + [{"type": "text", "text": warning}]
        else:
            new_content = str(result.content) + warning
        return ToolMessage(
            content=new_content,
            tool_call_id=result.tool_call_id,
            name=result.name,
            status=result.status,
        )

    # ------------------------------------------------------------------
    # Input sanitisation
    # ------------------------------------------------------------------

    def _validate_input(self, command: str) -> str | None:
        """Return ``None`` if *command* is acceptable, else a rejection reason."""
        if not command.strip():
            return "empty command"
        if len(command) > self._MAX_COMMAND_LENGTH:
            return "command too long"
        if "\x00" in command:
            return "null byte detected"
        return None

    # ------------------------------------------------------------------
    # Core logic (shared between sync and async paths)
    # ------------------------------------------------------------------

    def _pre_process(self, request: ToolCallRequest) -> tuple[str, str | None, AuditVerdict, AuditPattern | None, str | None]:
        """Classify the command and decide what to do.

        Returns ``(command, thread_id, verdict, matched_pattern, reject_reason)``.
        ``reject_reason`` is non-``None`` only for input-sanitisation
        rejections, in which case ``verdict`` is :data:`AuditVerdict.BLOCK`.
        """
        args = request.tool_call.get("args", {})
        raw_command = args.get("command")
        command = raw_command if isinstance(raw_command, str) else ""
        thread_id = self._get_thread_id(request)

        high = self._rules.get_high_risk_patterns()
        medium = self._rules.get_medium_risk_patterns()

        # ① input sanitisation — reject malformed input before regex analysis
        reject_reason = self._validate_input(command)
        if reject_reason:
            self._write_audit(thread_id, command, AuditVerdict.BLOCK, truncate=True)
            logger.warning("[SandboxAudit] INVALID INPUT thread=%s reason=%s", thread_id, reject_reason)
            return command, thread_id, AuditVerdict.BLOCK, None, reject_reason

        # ② classify command
        verdict, matched = _classify_command(command, high, medium)

        # ③ audit log
        self._write_audit(thread_id, command, verdict)

        if verdict == AuditVerdict.BLOCK:
            logger.warning("[SandboxAudit] BLOCKED thread=%s cmd=%r", thread_id, command)
        elif verdict == AuditVerdict.WARN:
            logger.warning("[SandboxAudit] WARN (medium-risk) thread=%s cmd=%r", thread_id, command)

        return command, thread_id, verdict, matched, None

    # ------------------------------------------------------------------
    # wrap_tool_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != self._tool_name:
            return handler(request)

        command, _, verdict, matched, reject_reason = self._pre_process(request)
        if verdict == AuditVerdict.BLOCK:
            reason = reject_reason or (matched.description if matched else "security violation detected")
            return self._build_block_message(request, reason)
        result = handler(request)
        if verdict == AuditVerdict.WARN:
            result = self._append_warn_to_result(result, command)
        return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if request.tool_call.get("name") != self._tool_name:
            return await handler(request)

        command, _, verdict, matched, reject_reason = self._pre_process(request)
        if verdict == AuditVerdict.BLOCK:
            reason = reject_reason or (matched.description if matched else "security violation detected")
            return self._build_block_message(request, reason)
        result = await handler(request)
        if verdict == AuditVerdict.WARN:
            result = self._append_warn_to_result(result, command)
        return result
