"""Unit tests for :mod:`agent_sdk.sandbox.base`.

Covers the :class:`Sandbox` and :class:`SandboxProvider` ABCs
plus the :class:`GrepMatch` dataclass. The tests do **not**
exercise a real sandbox — they verify the contracts that any
concrete implementation must satisfy, plus a tiny reference
backend that does in-memory I/O.
"""

from __future__ import annotations

import inspect

import pytest
from agent_sdk.sandbox.base import GrepMatch, Sandbox, SandboxProvider

# ---------------------------------------------------------------------------
# GrepMatch dataclass
# ---------------------------------------------------------------------------


class TestGrepMatch:
    def test_construction(self) -> None:
        m = GrepMatch(path="/tmp/a.py", line_number=3, line="hello")
        assert m.path == "/tmp/a.py"
        assert m.line_number == 3
        assert m.line == "hello"

    def test_frozen(self) -> None:
        m = GrepMatch(path="/tmp/a.py", line_number=1, line="x")
        with pytest.raises(Exception):
            m.line_number = 99  # type: ignore[misc]

    def test_equality(self) -> None:
        a = GrepMatch(path="/p", line_number=1, line="x")
        b = GrepMatch(path="/p", line_number=1, line="x")
        assert a == b

    def test_inequality(self) -> None:
        a = GrepMatch(path="/p", line_number=1, line="x")
        b = GrepMatch(path="/p", line_number=2, line="x")
        assert a != b


# ---------------------------------------------------------------------------
# Sandbox ABC
# ---------------------------------------------------------------------------


class _InMemorySandbox(Sandbox):
    """Tiny in-memory sandbox used to verify the ABC contract."""

    def __init__(self, id: str) -> None:  # noqa: A002
        super().__init__(id)
        self._files: dict[str, str] = {}
        self.executed: list[str] = []

    def execute_command(self, command: str) -> str:
        self.executed.append(command)
        return f"ran:{command}"

    def read_file(self, path: str) -> str:
        return self._files[path]

    def read_file_bytes(self, path: str) -> bytes:
        return self._files[path].encode("utf-8")

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        return sorted(k for k in self._files if k.startswith(path))

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self._files[path] = (self._files.get(path, "") if append else "") + content

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        import fnmatch

        matches = [p for p in self._files if p.startswith(path) and fnmatch.fnmatch(p[len(path) :].lstrip("/"), pattern)]
        truncated = len(matches) > max_results
        return matches[:max_results], truncated

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        import re

        regex_source = re.escape(pattern) if literal else pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(regex_source, flags)
        results: list[GrepMatch] = []
        for p, content in self._files.items():
            if not p.startswith(path):
                continue
            for n, line in enumerate(content.splitlines(), start=1):
                if compiled.search(line):
                    results.append(GrepMatch(path=p, line_number=n, line=line))
                    if len(results) >= max_results:
                        return results, True
        return results, False

    def update_file(self, path: str, content: bytes) -> None:
        self._files[path] = content.decode("utf-8")


class TestSandboxABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Sandbox(id="x")  # type: ignore[abstract]

    def test_id_property(self) -> None:
        sb = _InMemorySandbox(id="thread-42")
        assert sb.id == "thread-42"
        # id is read-only
        with pytest.raises(Exception):
            sb.id = "other"  # type: ignore[misc]

    def test_concrete_implementation_runs(self) -> None:
        sb = _InMemorySandbox(id="t1")
        assert sb.execute_command("echo hi") == "ran:echo hi"
        assert sb.executed == ["echo hi"]

    def test_abstract_methods_listed(self) -> None:
        names = {m for m in Sandbox.__abstractmethods__}
        assert names == {
            "execute_command",
            "read_file",
            "read_file_bytes",
            "list_dir",
            "write_file",
            "glob",
            "grep",
            "update_file",
        }

    def test_init_signature(self) -> None:
        sig = inspect.signature(Sandbox.__init__)
        params = list(sig.parameters)
        assert params == ["self", "id"]


# ---------------------------------------------------------------------------
# SandboxProvider ABC
# ---------------------------------------------------------------------------


class _CountingProvider(SandboxProvider):
    """Provider that hands out unique fake sandboxes."""

    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self._store: dict[str, Sandbox] = {}
        self.released: list[str] = []
        self.shut_down = False

    def acquire(self, thread_id: str | None = None) -> str:
        self._counter += 1
        sid = f"sb-{self._counter}"
        self._store[sid] = _InMemorySandbox(id=sid)
        return sid

    def get(self, sandbox_id: str) -> Sandbox | None:
        return self._store.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        self._store.pop(sandbox_id, None)
        self.released.append(sandbox_id)

    def shutdown(self) -> None:
        self.shut_down = True
        self._store.clear()


class TestSandboxProviderABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            SandboxProvider()  # type: ignore[abstract]

    def test_uses_thread_data_mounts_default(self) -> None:
        # Class-level default is False; subclasses can override.
        assert SandboxProvider.uses_thread_data_mounts is False

    def test_concrete_lifecycle(self) -> None:
        provider = _CountingProvider()
        sid = provider.acquire(thread_id="t-1")
        assert sid == "sb-1"
        sb = provider.get(sid)
        assert sb is not None
        assert isinstance(sb, Sandbox)
        # Release removes from store
        provider.release(sid)
        assert provider.get(sid) is None
        assert provider.released == [sid]

    def test_get_unknown_returns_none(self) -> None:
        provider = _CountingProvider()
        assert provider.get("does-not-exist") is None

    def test_release_unknown_is_noop(self) -> None:
        provider = _CountingProvider()
        # Should not raise; should be a tolerant operation.
        provider.release("does-not-exist")
        assert provider.released == ["does-not-exist"]

    def test_shutdown_default_is_noop(self) -> None:
        # Subclass with no override still satisfies Protocol but
        # inherits the default no-op shutdown.
        class _PlainProvider(SandboxProvider):
            def acquire(self, thread_id: str | None = None) -> str:
                return "x"

            def get(self, sandbox_id: str) -> Sandbox | None:
                return None

            def release(self, sandbox_id: str) -> None:
                return None

        p = _PlainProvider()
        # Default shutdown must exist and be a no-op
        p.shutdown()
        assert p.uses_thread_data_mounts is False

    def test_abstract_methods_listed(self) -> None:
        assert SandboxProvider.__abstractmethods__ == frozenset({"acquire", "get", "release"})

    def test_subclass_can_override_uses_thread_data_mounts(self) -> None:
        class _MountedProvider(_CountingProvider):
            uses_thread_data_mounts = True

        p = _MountedProvider()
        assert p.uses_thread_data_mounts is True


# ---------------------------------------------------------------------------
# Cross-cutting: Sandbox & Provider integrate as designed
# ---------------------------------------------------------------------------


class TestSandboxProviderIntegration:
    def test_acquire_then_use_then_release(self) -> None:
        provider = _CountingProvider()
        sid = provider.acquire(thread_id="t")
        sb = provider.get(sid)
        assert sb is not None

        sb.write_file("/tmp/hello.txt", "hi")
        assert sb.read_file("/tmp/hello.txt") == "hi"
        assert sb.execute_command("cat /tmp/hello.txt") == "ran:cat /tmp/hello.txt"

        provider.release(sid)
        assert provider.get(sid) is None

    def test_multiple_independent_sandboxes(self) -> None:
        provider = _CountingProvider()
        a = provider.acquire()
        b = provider.acquire()
        assert a != b
        sa, sb = provider.get(a), provider.get(b)
        assert sa is not None and sb is not None
        sa.write_file("/k", "from-a")
        sb.write_file("/k", "from-b")
        assert sa.read_file("/k") == "from-a"
        assert sb.read_file("/k") == "from-b"
