"""AIO sandbox — Docker-based sandbox provider for agent_sdk.

Provides :class:`AioSandboxProvider` and :class:`AioSandbox` —
production-grade sandbox implementations backed by the AIO sandbox
Docker image.

Requires: ``agent-sandbox`` (``uv add agent-sandbox``)

Usage::

    from agent_sdk.community.aio_sandbox import AioSandboxProvider

    provider = AioSandboxProvider(
        thread_base_dir=Path("./workspace"),
    )
"""

from agent_sdk.community.aio_sandbox.backend import (
    LocalContainerBackend,
    RemoteSandboxBackend,
    SandboxBackend,
    SandboxInfo,
    wait_for_sandbox_ready,
)
from agent_sdk.community.aio_sandbox.provider import AioSandboxProvider
from agent_sdk.community.aio_sandbox.sandbox import AioSandbox

__all__ = [
    "AioSandbox",
    "AioSandboxProvider",
    "LocalContainerBackend",
    "RemoteSandboxBackend",
    "SandboxBackend",
    "SandboxInfo",
    "wait_for_sandbox_ready",
]