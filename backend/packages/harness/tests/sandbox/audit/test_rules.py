"""Unit tests for :class:`agent_sdk.sandbox.audit.rules`.

Covers the :class:`AuditPattern` dataclass (validation of
``risk_level``) and the :class:`AuditRules` Protocol shape
(``runtime_checkable`` membership, methods gettable).
"""

from __future__ import annotations

import re

import pytest
from agent_sdk.sandbox.audit.default import DefaultAuditRules
from agent_sdk.sandbox.audit.rules import (
    AuditPattern,
    AuditRules,
    AuditVerdict,
)


class TestAuditVerdict:
    def test_values_are_strings(self) -> None:
        assert AuditVerdict.BLOCK.value == "block"
        assert AuditVerdict.WARN.value == "warn"
        assert AuditVerdict.PASS.value == "pass"

    def test_inherits_from_str(self) -> None:
        # AuditVerdict is used as both an enum and a wire-format
        # string in the audit log; ensure the str() cast works.
        assert str(AuditVerdict.BLOCK) == "AuditVerdict.BLOCK"


class TestAuditPattern:
    def test_valid_risk_levels(self) -> None:
        for level in ("high", "medium", "low"):
            pat = AuditPattern(re.compile(r"x"), level, "desc")
            assert pat.risk_level == level

    def test_invalid_risk_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid risk_level"):
            AuditPattern(re.compile(r"x"), "critical", "desc")

    def test_frozen(self) -> None:
        pat = AuditPattern(re.compile(r"x"), "high", "desc")
        with pytest.raises(Exception):
            pat.risk_level = "low"  # type: ignore[misc]

    def test_pattern_can_be_compiled(self) -> None:
        # Sanity check that the compiled regex actually searches.
        pat = AuditPattern(re.compile(r"rm\s+-rf"), "high", "rm -rf")
        assert pat.pattern.search("rm -rf /") is not None
        assert pat.pattern.search("rm -i file") is None


class TestAuditRulesProtocol:
    def test_default_implementation_satisfies_protocol(self) -> None:
        # runtime_checkable: isinstance check works on any class
        # that exposes the three required methods.
        rules: AuditRules = DefaultAuditRules()
        assert isinstance(rules, AuditRules)

    def test_get_high_risk_patterns_returns_list(self) -> None:
        rules = DefaultAuditRules()
        assert isinstance(rules.get_high_risk_patterns(), list)

    def test_get_medium_risk_patterns_returns_list(self) -> None:
        rules = DefaultAuditRules()
        assert isinstance(rules.get_medium_risk_patterns(), list)

    def test_get_low_risk_patterns_returns_list(self) -> None:
        rules = DefaultAuditRules()
        assert isinstance(rules.get_low_risk_patterns(), list)

    def test_custom_implementation_satisfies_protocol(self) -> None:
        class MyRules:
            def get_high_risk_patterns(self) -> list[AuditPattern]:
                return []

            def get_medium_risk_patterns(self) -> list[AuditPattern]:
                return []

            def get_low_risk_patterns(self) -> list[AuditPattern]:
                return []

        rules: AuditRules = MyRules()
        assert isinstance(rules, AuditRules)


class TestDefaultAuditRules:
    def test_all_lists_are_empty(self) -> None:
        rules = DefaultAuditRules()
        assert rules.get_high_risk_patterns() == []
        assert rules.get_medium_risk_patterns() == []
        assert rules.get_low_risk_patterns() == []

    def test_lists_are_independent(self) -> None:
        # Mutating the returned list MUST NOT corrupt subsequent
        # reads (the implementation should defensively copy or
        # return a fresh list).
        rules = DefaultAuditRules()
        rules.get_high_risk_patterns().append("not a pattern")
        assert rules.get_high_risk_patterns() == []
