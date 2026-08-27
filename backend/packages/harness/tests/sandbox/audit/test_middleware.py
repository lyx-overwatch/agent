"""Unit tests for :class:`agent_sdk.sandbox.audit.SandboxAuditMiddleware`.

Exercises the ``wrap_tool_call`` and ``awrap_tool_call`` hooks
with hand-rolled :class:`ToolCallRequest` instances, plus the
input-sanitisation paths (empty / too long / null bytes).
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any

import pytest
from agent_sdk.sandbox.audit.default import DefaultAuditRules
from agent_sdk.sandbox.audit.middleware import SandboxAuditMiddleware
from agent_sdk.sandbox.audit.rules import AuditPattern
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _StubRules:
    """A minimal :class:`AuditRules` for tests."""

    def __init__(self, high: list[AuditPattern] | None = None, medium: list[AuditPattern] | None = None) -> None:
        self._high = high or []
        self._medium = medium or []

    def get_high_risk_patterns(self) -> list[AuditPattern]:
        return self._high

    def get_medium_risk_patterns(self) -> list[AuditPattern]:
        return self._medium

    def get_low_risk_patterns(self) -> list[AuditPattern]:
        return []


def _make_request(
    tool_name: str,
    command: str,
    call_id: str = "call-1",
    runtime: Any = None,
    thread_id: str | None = "thread-1",
) -> ToolCallRequest:
    """Build a minimal :class:`ToolCallRequest` for tests.

    If *runtime* is not given, a :class:`SimpleNamespace` is
    constructed that exposes the ``context`` / ``config`` paths
    the middleware uses to look up ``thread_id``.
    """
    if runtime is None:
        runtime = SimpleNamespace(
            context={"thread_id": thread_id} if thread_id is not None else {},
            config={"configurable": {"thread_id": thread_id}} if thread_id is not None else {},
            state={},
        )
    return ToolCallRequest(
        tool_call={
            "name": tool_name,
            "args": {"command": command},
            "id": call_id,
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=runtime,
    )


def _ok_handler(req: ToolCallRequest) -> ToolMessage:
    """Sync handler that returns a fixed ToolMessage."""
    return ToolMessage(
        content="command output",
        tool_call_id=str(req.tool_call.get("id") or "missing_id"),
        name=str(req.tool_call.get("name") or "bash"),
    )


async def _ok_async_handler(req: ToolCallRequest) -> ToolMessage:
    """Async handler that mirrors :func:`_ok_handler`."""
    return _ok_handler(req)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_uses_default_rules(self) -> None:
        mw = SandboxAuditMiddleware()
        # Empty rules → every command passes.
        assert mw._rules.get_high_risk_patterns() == []

    def test_custom_rules_are_stored(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm"), "high", "rm")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        assert mw._rules is rules

    def test_custom_tool_name(self) -> None:
        mw = SandboxAuditMiddleware(tool_name="run_shell")
        # The middleware only audits calls to the configured name.
        assert mw._tool_name == "run_shell"


# ---------------------------------------------------------------------------
# wrap_tool_call (sync)
# ---------------------------------------------------------------------------


class TestWrapToolCall:
    def test_passes_through_non_target_tool(self) -> None:
        mw = SandboxAuditMiddleware(audit_rules=_StubRules(high=[AuditPattern(re.compile(r"rm"), "high", "rm")]))
        request = _make_request("read_file", "should be ignored")
        seen: list[ToolCallRequest] = []

        def handler(req: ToolCallRequest) -> ToolMessage:
            seen.append(req)
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert isinstance(result, ToolMessage)
        assert result.content == "command output"
        assert seen == [request]

    def test_safe_command_calls_handler(self) -> None:
        mw = SandboxAuditMiddleware(audit_rules=DefaultAuditRules())
        request = _make_request("bash", "ls -la")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert called
        assert result.content == "command output"

    def test_high_risk_command_returns_error_tool_message(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm\s+-rf\s+/"), "high", "rm -rf /")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "rm -rf /")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert not called
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "rm -rf /" in result.content

    def test_medium_risk_command_calls_handler_and_appends_warning(self) -> None:
        rules = _StubRules(medium=[AuditPattern(re.compile(r"\bchmod\s+777\b"), "medium", "chmod 777")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "chmod 777 /tmp/x")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert called
        assert isinstance(result, ToolMessage)
        assert "command output" in result.content
        assert "Warning" in result.content
        assert "chmod 777 /tmp/x" in result.content

    def test_empty_command_is_blocked(self) -> None:
        mw = SandboxAuditMiddleware()
        request = _make_request("bash", "   ")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert not called
        assert result.status == "error"
        assert "empty" in result.content

    def test_null_byte_is_blocked(self) -> None:
        mw = SandboxAuditMiddleware()
        request = _make_request("bash", "ls\x00-la")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert not called
        assert result.status == "error"
        assert "null byte" in result.content

    def test_oversize_command_is_blocked(self) -> None:
        mw = SandboxAuditMiddleware()
        big = "a" * (SandboxAuditMiddleware._MAX_COMMAND_LENGTH + 1)
        request = _make_request("bash", big)
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert not called
        assert result.status == "error"
        assert "too long" in result.content

    def test_custom_tool_name_is_audited(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm\s+-rf"), "high", "rm -rf")])
        mw = SandboxAuditMiddleware(audit_rules=rules, tool_name="run_shell")

        # A call to "bash" is now ignored; "run_shell" is audited.
        bash_request = _make_request("bash", "rm -rf /")
        result = mw.wrap_tool_call(bash_request, _ok_handler)
        # The default handler still ran because the name didn't match.
        assert isinstance(result, ToolMessage)
        assert result.content == "command output"

        run_shell_request = _make_request("run_shell", "rm -rf /")
        result = mw.wrap_tool_call(run_shell_request, _ok_handler)
        assert result.status == "error"

    def test_compound_command_with_blocked_subcommand(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm\s+-rf\s+/"), "high", "rm -rf /")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "ls; rm -rf /")
        called = False

        def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = mw.wrap_tool_call(request, handler)
        assert not called
        assert result.status == "error"

    def test_warning_does_not_mutate_handler_result_id(self) -> None:
        # The middleware must not change the tool_call_id of the
        # wrapped result, otherwise the LLM's tool-call tracking
        # would break.
        rules = _StubRules(medium=[AuditPattern(re.compile(r"\bchmod\s+777\b"), "medium", "chmod 777")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "chmod 777 /tmp/x", call_id="call-42")

        result = mw.wrap_tool_call(request, _ok_handler)
        assert isinstance(result, ToolMessage)
        # The handler reads ``request.tool_call["id"]`` and
        # forwards it as ``tool_call_id`` on the ToolMessage; the
        # middleware must preserve that id when appending the
        # warning.
        assert result.tool_call_id == "call-42"


# ---------------------------------------------------------------------------
# awrap_tool_call (async)
# ---------------------------------------------------------------------------


class TestAsyncWrapToolCall:
    def test_safe_command_calls_async_handler(self) -> None:
        mw = SandboxAuditMiddleware(audit_rules=DefaultAuditRules())
        request = _make_request("bash", "ls")
        result = asyncio.run(mw.awrap_tool_call(request, _ok_async_handler))
        assert isinstance(result, ToolMessage)
        assert result.content == "command output"

    def test_high_risk_command_blocked(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm\s+-rf"), "high", "rm -rf")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "rm -rf /")
        called = False

        async def handler(req: ToolCallRequest) -> ToolMessage:
            nonlocal called
            called = True
            return _ok_handler(req)

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert not called
        assert result.status == "error"

    def test_medium_risk_command_appends_warning(self) -> None:
        rules = _StubRules(medium=[AuditPattern(re.compile(r"\bpip\s+install\b"), "medium", "pip install")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        request = _make_request("bash", "pip install x")

        async def handler(req: ToolCallRequest) -> ToolMessage:
            return _ok_handler(req)

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert "Warning" in result.content


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_thread_id_appears_in_log(self, caplog: pytest.LogCaptureFixture) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm"), "high", "rm")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        # Build a runtime with a non-default thread id; ``_make_request``
        # puts the id in both ``context`` and ``config.configurable``.
        request = _make_request("bash", "rm -rf /", thread_id="thread-xyz")
        mw.wrap_tool_call(request, _ok_handler)

        # The middleware logs each classification. We do not
        # assert on the exact JSON, just that *some* log record
        # was emitted at INFO level with the thread id.
        all_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "thread-xyz" in all_text
        assert "BLOCKED" in all_text

    def test_audit_log_handles_missing_runtime(self) -> None:
        rules = _StubRules(high=[AuditPattern(re.compile(r"rm"), "high", "rm")])
        mw = SandboxAuditMiddleware(audit_rules=rules)
        # runtime=None is allowed in tests.
        request = _make_request("bash", "rm -rf /", runtime=None)
        result = mw.wrap_tool_call(request, _ok_handler)
        assert result.status == "error"
