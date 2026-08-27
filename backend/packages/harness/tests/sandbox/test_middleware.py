"""Unit tests for :class:`agent_sdk.sandbox.SandboxMiddleware`."""

from __future__ import annotations

from agent_sdk.sandbox.base import Sandbox, SandboxProvider
from agent_sdk.sandbox.middleware import SandboxMiddleware


class _InMemoryProvider(SandboxProvider):
    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self._store: dict[str, Sandbox] = {}
        self.acquired: list[str | None] = []
        self.released: list[str] = []

    def acquire(self, thread_id=None):
        self._counter += 1
        sid = f"sb-{self._counter}"
        self._store[sid] = _StubSandbox(sid)
        self.acquired.append(thread_id)
        return sid

    def get(self, sandbox_id):
        return self._store.get(sandbox_id)

    def release(self, sandbox_id):
        self._store.pop(sandbox_id, None)
        self.released.append(sandbox_id)


class _StubSandbox(Sandbox):
    def execute_command(self, command):
        return ""

    def read_file(self, path):
        return ""

    def read_file_bytes(self, path):
        return b""

    def list_dir(self, path, max_depth=2):
        return []

    def write_file(self, path, content, append=False):
        return None

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
        return [], False

    def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):

        return [], False

    def update_file(self, path, content):
        return None


class _FakeRuntime:
    def __init__(self, context=None) -> None:
        self.context = context or {}


class TestSandboxMiddleware:
    def test_lazy_init_noop_in_before_agent(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=True)
        result = mw.before_agent({}, runtime=_FakeRuntime({"thread_id": "t"}))
        assert result is None or result == {}
        # The provider MUST NOT have been touched.
        assert provider.acquired == []

    def test_eager_init_acquires_sandbox(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=False)
        result = mw.before_agent({}, runtime=_FakeRuntime({"thread_id": "t"}))
        assert result is not None
        assert result.get("sandbox", {}).get("sandbox_id") == "sb-1"
        assert provider.acquired == ["t"]

    def test_eager_init_no_thread_id_noop(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=False)
        result = mw.before_agent({}, runtime=_FakeRuntime({}))
        # No thread_id, no acquisition.
        assert result is None or result == {}
        assert provider.acquired == []

    def test_eager_init_skips_when_already_bound(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=False)
        # State already has a sandbox bound.
        result = mw.before_agent(
            {"sandbox": {"sandbox_id": "existing"}},
            runtime=_FakeRuntime({"thread_id": "t"}),
        )
        assert result is None or result == {}
        assert provider.acquired == []

    def test_after_agent_releases_state_sandbox(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=True)
        mw.after_agent(
            {"sandbox": {"sandbox_id": "sb-1"}},
            runtime=_FakeRuntime(),
        )
        assert provider.released == ["sb-1"]

    def test_after_agent_releases_context_sandbox(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=True)
        mw.after_agent({}, runtime=_FakeRuntime({"sandbox_id": "ctx-sb"}))
        assert provider.released == ["ctx-sb"]

    def test_after_agent_noop_when_nothing_to_release(self) -> None:
        provider = _InMemoryProvider()
        mw = SandboxMiddleware(provider=provider, lazy_init=True)
        mw.after_agent({}, runtime=_FakeRuntime({}))
        assert provider.released == []
