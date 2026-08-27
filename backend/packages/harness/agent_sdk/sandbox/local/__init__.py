"""Local subprocess-based sandbox (development only).

Provides :class:`LocalSandboxProvider` and :class:`LocalSandbox` —
minimal implementations of the agent_sdk ``SandboxProvider`` /
``Sandbox`` ABCs backed by Python ``subprocess``.

**Not safe for production** — the agent can access any file on the
host.  Use :class:`agent_sdk.community.aio_sandbox.AioSandboxProvider`
for production deployments.
"""

from agent_sdk.sandbox.local.provider import LocalSandbox, LocalSandboxProvider

__all__ = ["LocalSandbox", "LocalSandboxProvider"]