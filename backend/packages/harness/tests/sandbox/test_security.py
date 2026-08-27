"""Unit tests for :mod:`agent_sdk.sandbox.security`."""

from __future__ import annotations

from agent_sdk.sandbox.security import (
    DEFAULT_HOST_BASH_POLICY_FACTORY,
    LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE,
    LOCAL_HOST_BASH_DISABLED_MESSAGE,
    ConfigurableHostBashPolicy,
    DefaultHostBashPolicy,
    HostBashPolicy,
    default_host_bash_policy,
)

# ---------------------------------------------------------------------------
# Constants (verbatim from backend)
# ---------------------------------------------------------------------------


class TestMessages:
    def test_host_bash_disabled_message_is_stable(self) -> None:
        # Per ADR-011 the user-visible message is brand-neutral by default.
        # The LLM may key off the opening phrase, so we keep that stable.
        assert "Host bash execution is disabled" in LOCAL_HOST_BASH_DISABLED_MESSAGE
        # No DeerFlow-private product names in the default message.
        assert "AioSandboxProvider" not in LOCAL_HOST_BASH_DISABLED_MESSAGE
        # The fallback must be exposed under the new explicit name too.
        from agent_sdk.sandbox.security import LOCAL_BASH_DISABLED_MESSAGE_FALLBACK

        assert LOCAL_HOST_BASH_DISABLED_MESSAGE == LOCAL_BASH_DISABLED_MESSAGE_FALLBACK

    def test_subagent_message_is_stable(self) -> None:
        assert "Bash subagent is disabled" in LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE
        # Per ADR-011 the default subagent gate message is also brand-neutral.
        assert "AioSandboxProvider" not in LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE
        from agent_sdk.sandbox.security import (
            LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK,
        )

        assert LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE == LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK

    def test_messages_are_distinct(self) -> None:
        assert LOCAL_HOST_BASH_DISABLED_MESSAGE != LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE


# ---------------------------------------------------------------------------
# DefaultHostBashPolicy
# ---------------------------------------------------------------------------


class TestDefaultPolicy:
    def test_always_denies(self) -> None:
        policy = DefaultHostBashPolicy()
        assert policy.is_host_bash_allowed() is False

    def test_default_factory_returns_default(self) -> None:
        policy = default_host_bash_policy()
        assert isinstance(policy, DefaultHostBashPolicy)
        assert policy.is_host_bash_allowed() is False

    def test_default_factory_alias(self) -> None:
        # The constant the tools module imports must point at the same factory.
        assert DEFAULT_HOST_BASH_POLICY_FACTORY is default_host_bash_policy


# ---------------------------------------------------------------------------
# ConfigurableHostBashPolicy
# ---------------------------------------------------------------------------


class TestConfigurablePolicy:
    def test_passes_through_allow_fn(self) -> None:
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        assert policy.is_host_bash_allowed() is True

    def test_passes_through_deny_fn(self) -> None:
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: False)
        assert policy.is_host_bash_allowed() is False

    def test_truthy_non_bool_coerced_to_true(self) -> None:
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: "yes")
        assert policy.is_host_bash_allowed() is True

    def test_falsy_non_bool_coerced_to_false(self) -> None:
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: 0)
        assert policy.is_host_bash_allowed() is False

    def test_exception_in_allow_fn_yields_false(self) -> None:
        def boom() -> bool:
            raise RuntimeError("config not loaded")

        policy = ConfigurableHostBashPolicy(allow_fn=boom)
        # Safe default: an exception is treated as "deny".
        assert policy.is_host_bash_allowed() is False

    def test_consulted_each_call(self) -> None:
        """The policy is consulted every call, not memoised."""
        state = {"allowed": False}
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: state["allowed"])
        assert policy.is_host_bash_allowed() is False
        state["allowed"] = True
        assert policy.is_host_bash_allowed() is True
        state["allowed"] = False
        assert policy.is_host_bash_allowed() is False


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_default_is_host_bash_policy(self) -> None:
        assert isinstance(DefaultHostBashPolicy(), HostBashPolicy)

    def test_configurable_is_host_bash_policy(self) -> None:
        assert isinstance(ConfigurableHostBashPolicy(lambda: True), HostBashPolicy)

    def test_protocol_is_runtime_checkable(self) -> None:
        class _Other:
            def is_host_bash_allowed(self) -> bool:
                return True

            @property
            def disabled_message(self) -> str:
                return "stub"

        assert isinstance(_Other(), HostBashPolicy)


# ---------------------------------------------------------------------------
# 5.7 batch-7 cleanup (M-4: brand-neutral default + ConfigurableHostBashPolicy override)
# ---------------------------------------------------------------------------


class TestBrandNeutralDefault:
    """M-4: default deny message is brand-neutral (no DeerFlow product names)."""

    def test_default_host_bash_disabled_message_is_brand_neutral(self) -> None:
        from agent_sdk.sandbox.security import LOCAL_BASH_DISABLED_MESSAGE_FALLBACK

        msg = LOCAL_BASH_DISABLED_MESSAGE_FALLBACK
        # No DeerFlow-private product names.
        assert "AioSandboxProvider" not in msg
        assert "allow_host_bash" not in msg
        # Still tells the LLM how to enable.
        assert "ConfigurableHostBashPolicy" in msg

    def test_default_policy_returns_brand_neutral_message(self) -> None:
        policy = DefaultHostBashPolicy()
        assert policy.is_host_bash_allowed() is False
        assert "AioSandboxProvider" not in policy.disabled_message

    def test_configurable_policy_accepts_disabled_message_override(self) -> None:
        custom = "DeerFlow preset: enable sandbox.allow_host_bash in config.yaml"
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True, disabled_message=custom)
        assert policy.is_host_bash_allowed() is True
        assert policy.disabled_message == custom

    def test_configurable_policy_falls_back_to_brand_neutral_when_no_override(self) -> None:
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        assert "AioSandboxProvider" not in policy.disabled_message
