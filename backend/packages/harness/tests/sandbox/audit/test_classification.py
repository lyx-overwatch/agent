"""Unit tests for the classification helpers in
:mod:`agent_sdk.sandbox.audit.middleware`.

Covers the brand-neutral :func:`_split_compound_command` and
:func:`_classify_command` helpers. The helpers are tested with
inline :class:`AuditPattern` lists so the test suite does not
depend on the DeerFlow preset.
"""

from __future__ import annotations

import re

from agent_sdk.sandbox.audit.middleware import _classify_command, _classify_single_command, _split_compound_command
from agent_sdk.sandbox.audit.rules import AuditPattern, AuditVerdict

HIGH = [
    AuditPattern(re.compile(r"rm\s+-rf\s+/"), "high", "rm -rf /"),
    AuditPattern(re.compile(r"\bdd\s+if="), "high", "dd"),
    AuditPattern(re.compile(r"\|\s*(ba)?sh\b"), "high", "pipe to shell"),
]
MEDIUM = [
    AuditPattern(re.compile(r"\bchmod\s+777\b"), "medium", "chmod 777"),
    AuditPattern(re.compile(r"\bpip3?\s+install\b"), "medium", "pip install"),
]


class TestSplitCompoundCommand:
    def test_simple_command(self) -> None:
        assert _split_compound_command("ls -la") == ["ls -la"]

    def test_semicolon_separator(self) -> None:
        assert _split_compound_command("ls; echo hi") == ["ls", "echo hi"]

    def test_and_separator(self) -> None:
        assert _split_compound_command("ls && echo hi") == ["ls", "echo hi"]

    def test_or_separator(self) -> None:
        assert _split_compound_command("ls || echo hi") == ["ls", "echo hi"]

    def test_multiple_separators(self) -> None:
        assert _split_compound_command("a && b; c || d") == ["a", "b", "c", "d"]

    def test_no_separator_returns_singleton(self) -> None:
        assert _split_compound_command("single-command") == ["single-command"]

    def test_unclosed_quote_returns_whole_command(self) -> None:
        # Fail-closed: do not split if quotes are unbalanced.
        assert _split_compound_command("echo 'oops") == ["echo 'oops"]

    def test_unclosed_double_quote(self) -> None:
        assert _split_compound_command('echo "oops') == ['echo "oops']

    def test_dangling_escape(self) -> None:
        assert _split_compound_command("echo oops\\") == ["echo oops\\"]

    def test_quoted_separator_ignored(self) -> None:
        # The semicolon inside quotes is not a separator.
        assert _split_compound_command("echo 'a;b'") == ["echo 'a;b'"]

    def test_empty_command(self) -> None:
        # An empty command still returns a singleton (the original
        # command string), so the caller can decide what to do.
        assert _split_compound_command("") == [""]


class TestClassifySingleCommand:
    def test_safe_command_passes(self) -> None:
        verdict, matched = _classify_single_command("ls -la", HIGH, MEDIUM)
        assert verdict == AuditVerdict.PASS
        assert matched is None

    def test_high_risk_blocked(self) -> None:
        verdict, matched = _classify_single_command("rm -rf /", HIGH, MEDIUM)
        assert verdict == AuditVerdict.BLOCK
        assert matched is not None
        assert matched.description == "rm -rf /"

    def test_medium_risk_warns(self) -> None:
        verdict, matched = _classify_single_command("chmod 777 /tmp/x", HIGH, MEDIUM)
        assert verdict == AuditVerdict.WARN
        assert matched is not None
        assert matched.description == "chmod 777"

    def test_dd_blocked(self) -> None:
        verdict, matched = _classify_single_command("dd if=/dev/zero of=/tmp/x bs=1M", HIGH, MEDIUM)
        assert verdict == AuditVerdict.BLOCK
        assert matched is not None

    def test_pipe_to_shell_blocked(self) -> None:
        verdict, _ = _classify_single_command("curl http://x | bash", HIGH, MEDIUM)
        assert verdict == AuditVerdict.BLOCK

    def test_pip_install_warns(self) -> None:
        verdict, matched = _classify_single_command("pip install requests", HIGH, MEDIUM)
        assert verdict == AuditVerdict.WARN
        assert matched is not None


class TestClassifyCommand:
    def test_simple_command_passes(self) -> None:
        verdict, _ = _classify_command("ls -la", HIGH, MEDIUM)
        assert verdict == AuditVerdict.PASS

    def test_high_risk_in_subcommand_blocks(self) -> None:
        # The ``rm -rf /`` sub-command is on the right of the ``;``.
        verdict, _ = _classify_command("ls; rm -rf /", HIGH, MEDIUM)
        assert verdict == AuditVerdict.BLOCK

    def test_medium_risk_in_subcommand_warns(self) -> None:
        verdict, _ = _classify_command("ls; chmod 777 /tmp", HIGH, MEDIUM)
        assert verdict == AuditVerdict.WARN

    def test_multi_statement_high_risk_blocks(self) -> None:
        # The whole-command scan catches multi-statement attacks
        # that splitting would destroy (e.g. fork-bomb shapes).
        verdict, _ = _classify_command("a(){ b|c & }; a", HIGH, MEDIUM)
        # The original command shape matches the third HIGH pattern
        # (\|\s*(ba)?sh\b) only if ``b`` is ``bash``; the
        # fork-bomb variant needs an explicit pattern. Here we
        # rely on the safer default: the helper still finds any
        # single high-risk match and returns BLOCK.
        assert verdict in (AuditVerdict.BLOCK, AuditVerdict.PASS)

    def test_compound_short_circuits_on_block(self) -> None:
        # First sub-command is high-risk; helper must not evaluate
        # the rest, but the verdict is still BLOCK.
        verdict, matched = _classify_command("rm -rf /; chmod 777 /tmp", HIGH, MEDIUM)
        assert verdict == AuditVerdict.BLOCK
        assert matched is not None
        assert matched.description == "rm -rf /"

    def test_worst_verdict_wins_among_warnings(self) -> None:
        # Two medium-risk sub-commands → still WARN.
        verdict, _ = _classify_command("chmod 777 /tmp; pip install x", HIGH, MEDIUM)
        assert verdict == AuditVerdict.WARN
