"""Security policy for sandbox tool gating.

This module is a re-implementation (per ADR-010) of
``deerflow.sandbox.security``. The backend's
``is_host_bash_allowed(config)`` couples policy to a global
config singleton; the SDK decouples it via a
:class:`HostBashPolicy` Protocol so that any product can
inject its own policy without reaching into a global.

Two reference implementations are provided:

* :class:`DefaultHostBashPolicy` — always denies host bash
  execution. This is the **safe default**: a sandbox that
  runs commands on the host filesystem is not a security
  boundary, and a brand-neutral SDK should not silently
  expose the host to the agent.
* :class:`ConfigurableHostBashPolicy` — consults a callback
  that returns a boolean. Products that want to keep the
  backend's opt-in behaviour (``sandbox.allow_host_bash``)
  can pass a lambda that reads their own config.

Per ADR-011 the user-visible error message returned on
deny is **brand-neutral** (no DeerFlow product names like
``AioSandboxProvider``). Products that want the legacy
DeerFlow wording for a downstream preset can override
``disabled_message`` on :class:`ConfigurableHostBashPolicy`.

The :data:`LOCAL_HOST_BASH_DISABLED_MESSAGE` and
:data:`LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` constants are
**kept as backward-compat aliases** for code that imported
them from the backend module; they resolve to
:data:`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK`. New code
should use :attr:`HostBashPolicy.disabled_message`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

#: Brand-neutral fallback message returned by the default policy
#: when host bash execution is denied. Per ADR-011 it must NOT
#: name any DeerFlow-private product (e.g. ``AioSandboxProvider``).
#: Products that want a custom message can override
#: ``disabled_message`` on the policy instance.
LOCAL_BASH_DISABLED_MESSAGE_FALLBACK = (
    "Host bash execution is disabled by the host_bash policy because the active "
    "sandbox does not provide a secure boundary for executing commands on the host. "
    "Set host_bash_policy to ConfigurableHostBashPolicy(allow_fn=lambda: True) to "
    "enable host bash, or switch to a sandbox provider that isolates bash execution."
)

#: Brand-neutral fallback for the subagent host-bash gate.
LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK = (
    "Bash subagent is disabled by the host_bash policy because host bash execution "
    "is not a secure sandbox boundary. Set host_bash_policy to "
    "ConfigurableHostBashPolicy(allow_fn=lambda: True) to enable, or switch to a "
    "sandbox provider that isolates bash execution."
)

#: Backward-compat alias for :data:`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK`.
#: Originally a verbatim copy of ``deerflow.sandbox.security``'s
#: ``LOCAL_HOST_BASH_DISABLED_MESSAGE`` (which named
#: ``AioSandboxProvider`` and ``sandbox.allow_host_bash``). Per
#: ADR-011 the SDK ships a brand-neutral message; DeerFlow preset
#: in phase 4 will provide a DeerFlow-flavoured override on the
#: policy instance. This alias exists so legacy ``import`` sites
#: keep working.
LOCAL_HOST_BASH_DISABLED_MESSAGE = LOCAL_BASH_DISABLED_MESSAGE_FALLBACK

#: Backward-compat alias for :data:`LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK`.
LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE = LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK


@runtime_checkable
class HostBashPolicy(Protocol):
    """Decide whether host bash execution is allowed for the current call.

    Implementations are expected to be **stateless and cheap**
    — the policy is consulted on every ``bash`` tool call. A
    product that needs per-thread gating can stash thread
    state in a :class:`contextvars.ContextVar` and read it
    from inside the policy callable.
    """

    def is_host_bash_allowed(self) -> bool:
        """Return ``True`` to allow host bash, ``False`` to deny."""
        ...

    @property
    def disabled_message(self) -> str:
        """Message to return to the LLM when the policy denies.

        The default brand-neutral message is
        :data:`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK`. Products
        (e.g. DeerFlow preset in phase 4) override this on a
        :class:`ConfigurableHostBashPolicy` instance to inject
        product-specific guidance.
        """
        ...


class DefaultHostBashPolicy:
    """The safe default: deny host bash unconditionally.

    Used by :class:`agent_sdk.presets.deerflow.DeerFlowPathProvider`
    for a host-local sandbox. The backend's
    ``is_host_bash_allowed`` returns ``True`` for any
    non-local-sandbox provider; the SDK does the same via
    :class:`ConfigurableHostBashPolicy` (which downstream
    products can configure to match their environment).
    """

    def is_host_bash_allowed(self) -> bool:
        return False

    @property
    def disabled_message(self) -> str:
        return LOCAL_BASH_DISABLED_MESSAGE_FALLBACK


class ConfigurableHostBashPolicy:
    """Delegate to a user-supplied callable.

    Args:
        allow_fn: A zero-arg callable returning a boolean.
            Called on every ``bash`` tool invocation. The
            callable may consult a config singleton, a
            :class:`contextvars.ContextVar`, or any other
            thread/async-local state.
        disabled_message: Optional override of the message
            returned to the LLM when the policy denies.
            Defaults to the brand-neutral
            :data:`LOCAL_BASH_DISABLED_MESSAGE_FALLBACK`. Pass
            a product-specific string (e.g. from the DeerFlow
            preset) to expose brand guidance.

    Example::

        policy = ConfigurableHostBashPolicy(
            allow_fn=lambda: get_app_config().sandbox.allow_host_bash,
            disabled_message="DeerFlow preset: enable sandbox.allow_host_bash...",
        )
    """

    def __init__(self, allow_fn: callable, disabled_message: str | None = None) -> None:  # type: ignore[valid-type]
        self._allow_fn = allow_fn
        self._disabled_message = disabled_message or LOCAL_BASH_DISABLED_MESSAGE_FALLBACK

    def is_host_bash_allowed(self) -> bool:
        try:
            return bool(self._allow_fn())
        except Exception:
            return False

    @property
    def disabled_message(self) -> str:
        return self._disabled_message


def default_host_bash_policy() -> HostBashPolicy:
    """Return the brand-neutral default :class:`HostBashPolicy`.

    Exposed as a factory (rather than a module-level
    instance) so that tests can monkey-patch it. The
    default behaviour is :class:`DefaultHostBashPolicy`
    (always deny).
    """
    return DefaultHostBashPolicy()


#: Module-level alias used by :func:`agent_sdk.sandbox.tools.make_sandbox_tools`
#: as the default ``host_bash_policy`` argument. Tests can
#: patch this attribute to inject a custom policy.
DEFAULT_HOST_BASH_POLICY_FACTORY = default_host_bash_policy


__all__ = [
    "ConfigurableHostBashPolicy",
    "DEFAULT_HOST_BASH_POLICY_FACTORY",
    "DefaultHostBashPolicy",
    "HostBashPolicy",
    "LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE",
    "LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE_FALLBACK",
    "LOCAL_BASH_DISABLED_MESSAGE_FALLBACK",
    "LOCAL_HOST_BASH_DISABLED_MESSAGE",
    "default_host_bash_policy",
]
