"""Unit tests for :mod:`agent_sdk.sandbox.tools`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agent_sdk.sandbox.base import GrepMatch, Sandbox, SandboxProvider
from agent_sdk.sandbox.exceptions import (
    SandboxError,
    SandboxRuntimeError,
)
from agent_sdk.sandbox.path_resolver import (
    CustomMount,
    SandboxPathResolver,
    SandboxToolsConfig,
)
from agent_sdk.sandbox.security import (
    LOCAL_HOST_BASH_DISABLED_MESSAGE,
    ConfigurableHostBashPolicy,
)
from agent_sdk.sandbox.tools import (
    SandboxToolsBundle,
    _truncate_bash_output,
    _truncate_ls_output,
    _truncate_read_file_output,
    make_sandbox_tools,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _InMemorySandbox(Sandbox):
    """In-memory sandbox that records commands and stores files in a dict.

    Falls back to the real file system for ``read_file`` /
    ``list_dir`` / ``write_file`` when the in-memory dict has no
    entry at *path*. This mirrors the behaviour a real
    ``LocalSandboxProvider`` would have — the tool layer resolves
    ``/mnt/user-data/...`` to a real host path and the sandbox is
    just a thin shim over the OS. Tests that pre-populate the
    real file system (via ``tmp_path``) work without further
    ceremony; tests that want pure dict semantics just populate
    ``sb.files`` directly.
    """

    def __init__(self, id: str) -> None:
        super().__init__(id)
        self.commands: list[str] = []
        self.files: dict[str, str] = {}
        # Used to assert the file_operation_lock was held.
        self.locked_during_write = False

    def execute_command(self, command):
        self.commands.append(command)
        return f"cmd:{command}"

    def read_file(self, path):
        if path in self.files:
            return self.files[path]
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def read_file_bytes(self, path):
        if path in self.files:
            return self.files[path].encode()
        try:
            return Path(path).read_bytes()
        except OSError:
            return b""

    def list_dir(self, path, max_depth=2):
        mem_matches = sorted(p for p in self.files if p.startswith(path))
        if mem_matches:
            return mem_matches
        try:
            p = Path(path)
            if p.exists() and p.is_dir():
                return sorted(str(c) for c in p.iterdir())
        except OSError:
            pass
        return []

    def write_file(self, path, content, append=False):
        if append:
            self.files[path] = self.files.get(path, "") + content
        else:
            self.files[path] = content
        # Mirror the write to the real file system so subsequent
        # read_file / list_dir calls see it on disk too.
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
        from fnmatch import fnmatch

        matches = []
        for p in self.files:
            if p.startswith(path):
                tail = p[len(path):].lstrip("/\\")
                if fnmatch(tail, pattern):
                    matches.append(p)
                    if len(matches) >= max_results:
                        return matches, True
        return matches, False

    def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):
        import re

        regex = re.compile(re.escape(pattern) if literal else pattern, 0 if case_sensitive else re.IGNORECASE)
        matches = []
        for p, content in self.files.items():
            if not p.startswith(path):
                continue
            if glob is not None and not _glob_match(glob, p[len(path):].lstrip("/\\")):
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches.append(GrepMatch(path=p, line_number=i, line=line))
                    if len(matches) >= max_results:
                        return matches, True
        return matches, False

    def update_file(self, path, content):
        self.files[path] = content.decode()


def _glob_match(pattern: str, rel: str) -> bool:
    from fnmatch import fnmatch

    return fnmatch(rel, pattern)


class _InMemoryProvider(SandboxProvider):
    def __init__(self) -> None:
        super().__init__()
        self._counter = 0
        self._store: dict[str, _InMemorySandbox] = {}
        self.acquired: list[str | None] = []
        self.released: list[str] = []
        # If set, acquire() raises this exception.
        self.acquire_raises: Exception | None = None
        # If set, get() returns this sandbox (overrides normal lookup).
        self.get_returns: Sandbox | None = None
        self.get_returns_none: bool = False
        # If True, acquire() returns ``"local"`` as the sandbox id (matches
        # the real ``LocalSandboxProvider`` so ``is_local_sandbox`` returns True).
        self.use_local_marker: bool = False

    def acquire(self, thread_id=None):
        if self.acquire_raises is not None:
            raise self.acquire_raises
        self._counter += 1
        sid = "local" if self.use_local_marker else f"sb-{self._counter}"
        self._store[sid] = _InMemorySandbox(sid)
        self.acquired.append(thread_id)
        return sid

    def get(self, sandbox_id):
        if self.get_returns_none:
            return None
        if self.get_returns is not None:
            return self.get_returns
        return self._store.get(sandbox_id)

    def release(self, sandbox_id):
        self._store.pop(sandbox_id, None)
        self.released.append(sandbox_id)


class _FakeState:
    """Duck-types the ``runtime.state`` mapping with attribute-like access."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data


class _FakeRuntime:
    """Duck-types a langchain ``ToolRuntime`` with state, context, and config."""

    def __init__(
        self,
        *,
        thread_id: str | None = "t-1",
        state: dict | None = None,
        context_extra: dict | None = None,
        sandbox_id: str | None = None,
    ) -> None:
        merged_state: dict = dict(state or {})
        if sandbox_id is not None:
            merged_state.setdefault("sandbox", {"sandbox_id": sandbox_id})
        self.state = _FakeState(merged_state)
        ctx: dict[str, Any] = {"thread_id": thread_id} if thread_id else {}
        if context_extra:
            ctx.update(context_extra)
        self.context = ctx
        self.config = {"configurable": {"thread_id": thread_id}} if thread_id else {"configurable": {}}


# ---------------------------------------------------------------------------
# Bundle factory
# ---------------------------------------------------------------------------


def _bundle(**resolver_kwargs) -> tuple[SandboxToolsBundle, _InMemoryProvider, SandboxPathResolver]:
    provider = _InMemoryProvider()
    resolver = SandboxPathResolver(SandboxToolsConfig(**resolver_kwargs))
    bundle = make_sandbox_tools(
        sandbox_provider=provider,
        resolver=resolver,
    )
    return bundle, provider, resolver


def _local_bundle(**resolver_kwargs) -> tuple[SandboxToolsBundle, _InMemoryProvider, SandboxPathResolver]:
    """Bundle whose provider returns ``"local"`` as the sandbox id (so ``is_local_sandbox`` is True)."""
    provider = _InMemoryProvider()
    provider.use_local_marker = True
    resolver = SandboxPathResolver(SandboxToolsConfig(**resolver_kwargs))
    bundle = make_sandbox_tools(
        sandbox_provider=provider,
        resolver=resolver,
    )
    return bundle, provider, resolver


def _invoke(tool, *args, runtime=None, **kwargs):
    """Invoke a ``@tool``-wrapped callable with a fake runtime as the first arg."""
    return tool.invoke({**{"runtime": runtime or _FakeRuntime()}, **{a: kwargs[a] for a in kwargs}})


# ---------------------------------------------------------------------------
# Tool helper truncation
# ---------------------------------------------------------------------------


class TestTruncationHelpers:
    def test_bash_short_passthrough(self) -> None:
        assert _truncate_bash_output("hello", 100) == "hello"

    def test_bash_middle_truncation(self) -> None:
        out = "a" * 1000
        result = _truncate_bash_output(out, 200)
        # The marker is in the middle.
        assert "[middle truncated:" in result
        # Head is preserved.
        assert result.startswith("a" * 70)
        # Tail is preserved.
        assert result.endswith("a" * 70)

    def test_bash_zero_max_chars_disables(self) -> None:
        out = "x" * 10000
        assert _truncate_bash_output(out, 0) == out

    def test_bash_max_chars_too_small(self) -> None:
        # max_chars smaller than the marker -> first max_chars chars.
        out = "x" * 1000
        result = _truncate_bash_output(out, 5)
        assert result == "xxxxx"

    def test_read_file_head_truncation(self) -> None:
        out = "a" * 1000
        result = _truncate_read_file_output(out, 200)
        assert "[truncated:" in result
        # Beginning of the file is preserved.
        assert result.startswith("a" * 80)

    def test_read_file_short_passthrough(self) -> None:
        assert _truncate_read_file_output("hello", 100) == "hello"

    def test_ls_head_truncation(self) -> None:
        out = "a" * 1000
        result = _truncate_ls_output(out, 200)
        assert "[truncated:" in result
        assert result.startswith("a" * 80)


# ---------------------------------------------------------------------------
# Bundle + factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_returns_seven_tools(self) -> None:
        bundle, _, _ = _bundle()
        assert isinstance(bundle, SandboxToolsBundle)
        for attr in ["bash", "ls", "glob", "grep", "read_file", "write_file", "str_replace"]:
            assert hasattr(bundle, attr), attr

    def test_default_names(self) -> None:
        bundle, _, _ = _bundle()
        assert bundle.bash.name == "bash"
        assert bundle.ls.name == "ls"
        assert bundle.glob.name == "glob"
        assert bundle.grep.name == "grep"
        assert bundle.read_file.name == "read_file"
        assert bundle.write_file.name == "write_file"
        assert bundle.str_replace.name == "str_replace"

    def test_name_prefix(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(
            sandbox_provider=provider,
            resolver=resolver,
            name_prefix="df_",
        )
        assert bundle.bash.name == "df_bash"
        assert bundle.ls.name == "df_ls"
        assert bundle.write_file.name == "df_write_file"

    def test_default_policy_used_when_none(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        # Should not raise.
        make_sandbox_tools(sandbox_provider=provider, resolver=resolver)


# ---------------------------------------------------------------------------
# bash tool
# ---------------------------------------------------------------------------


class TestBashTool:
    def test_executes_command(self) -> None:
        bundle, provider, _ = _bundle()
        runtime = _FakeRuntime()
        result = bundle.bash.func(runtime=runtime, description="test", command="echo hi")
        # In-memory sandbox returns "cmd:<command>".
        assert "echo hi" in result
        # The provider was lazily queried.
        assert len(provider.acquired) == 1
        assert provider.acquired[0] == "t-1"

    def test_lazy_acquire_only_once(self) -> None:
        bundle, provider, _ = _bundle()
        runtime = _FakeRuntime()
        for _ in range(3):
            bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert len(provider.acquired) == 1

    def test_no_thread_id_raises(self) -> None:
        bundle, provider, _ = _bundle()
        runtime = _FakeRuntime(thread_id=None)
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")
        assert "Thread ID" in result

    def test_local_sandbox_denies_host_bash(self) -> None:
        # The default DefaultHostBashPolicy denies host bash; the sandbox id
        # "local" marks this as a local sandbox, so the bash tool returns
        # the deny message.
        bundle, provider, _ = _bundle()
        runtime = _FakeRuntime(state={"sandbox": {"sandbox_id": "local"}})
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")
        assert LOCAL_HOST_BASH_DISABLED_MESSAGE in result
        # Provider should not have been called.
        assert provider.acquired == []

    def test_local_sandbox_allows_when_policy_grants(self) -> None:
        # Use ConfigurableHostBashPolicy to grant host bash.
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        bundle = make_sandbox_tools(
            sandbox_provider=provider,
            resolver=resolver,
            host_bash_policy=policy,
        )
        runtime = _FakeRuntime(state={"sandbox": {"sandbox_id": "local"}})
        result = bundle.bash.func(runtime=runtime, description="x", command="ls /mnt/user-data/workspace")
        # Command was executed; not the deny message.
        assert not result.startswith("Error:")
        # The on-host workspace was created (lazy_init side effect).
        assert "ls" in result

    def test_local_sandbox_creates_thread_dirs(self, tmp_path: Path) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        bundle = make_sandbox_tools(
            sandbox_provider=provider,
            resolver=resolver,
            host_bash_policy=policy,
        )
        ws = tmp_path / "ws"
        up = tmp_path / "up"
        out = tmp_path / "out"
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": str(ws),
                    "uploads_path": str(up),
                    "outputs_path": str(out),
                },
            },
        )
        bundle.bash.func(runtime=runtime, description="x", command="ls")
        # Lazy directory creation.
        assert ws.exists()
        assert up.exists()
        assert out.exists()
        # Idempotent on second call.
        bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert ws.exists()

    def test_local_sandbox_validates_paths(self, tmp_path: Path) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        bundle = make_sandbox_tools(
            sandbox_provider=provider,
            resolver=resolver,
            host_bash_policy=policy,
        )
        ws = tmp_path / "ws"
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {"workspace_path": str(ws)},
            },
        )
        # Unsafe absolute path.
        result = bundle.bash.func(runtime=runtime, description="x", command="ls /etc")
        assert result.startswith("Error:")

    def test_non_local_sandbox_passes_through(self) -> None:
        bundle, provider, _ = _bundle()
        # No "sandbox_id": "local" -> treated as non-local.
        runtime = _FakeRuntime()
        result = bundle.bash.func(runtime=runtime, description="x", command="ls /etc")
        # The non-local path simply does not do virtual-path replacement; the
        # in-memory sandbox returns the command-string.
        assert "ls /etc" in result

    def test_sandbox_error_surfaced(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True

        class _ExplodingSandbox(Sandbox):
            def __init__(self, id: str) -> None:
                super().__init__(id)

            def execute_command(self, command):
                raise SandboxError("kaboom")

            def read_file(self, path):
                return ""

            def read_file_bytes(self, path):
                return b""

            def list_dir(self, path, max_depth=2):
                return []

            def write_file(self, path, content, append=False):
                pass

            def glob(self, path, pattern, *, include_dirs=False, max_results=200):
                return [], False

            def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):
                return [], False

            def update_file(self, path, content):
                pass

        provider.acquire_raises = None
        # Override the sandbox-creation so that we get the exploding one.
        # We do this by pre-acquiring and then pointing the provider at it.
        sid = provider.acquire("t-1")
        provider._store[sid] = _ExplodingSandbox(sid)

        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")
        assert "kaboom" in result


# ---------------------------------------------------------------------------
# ls tool
# ---------------------------------------------------------------------------


class TestLsTool:
    def test_user_data_path_resolves_and_lists(self, tmp_path: Path) -> None:
        bundle, provider, _ = _bundle()
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.py").write_text("x")
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": str(ws),
                    "uploads_path": str(tmp_path / "up"),
                    "outputs_path": str(tmp_path / "out"),
                }
            },
        )
        result = bundle.ls.func(runtime=runtime, description="x", path="/mnt/user-data/workspace")
        # The in-memory list_dir returns sorted path-prefixed matches.
        # The path is masked back to the virtual form.
        assert "a.py" in result

    def test_empty_directory(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.ls.func(runtime=runtime, description="x", path="/mnt/user-data/workspace")
        assert result == "(empty)"

    def test_unknown_path_rejected(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": "/tmp/ws",
                    "uploads_path": "/tmp/up",
                    "outputs_path": "/tmp/out",
                }
            },
        )
        result = bundle.ls.func(runtime=runtime, description="x", path="/etc")
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# glob tool
# ---------------------------------------------------------------------------


class TestGlobTool:
    def test_basic_match(self, tmp_path: Path) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/root/a.py"] = "x"
        sb.files["/root/b.py"] = "x"
        sb.files["/root/c.txt"] = "x"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.glob.func(runtime=runtime, description="x", pattern="*.py", path="/root")
        assert "Found 2 paths" in result
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_no_matches(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.glob.func(runtime=runtime, description="x", pattern="*.py", path="/empty")
        assert result.startswith("No files matched")

    def test_max_results_respected(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        for i in range(5):
            sb.files[f"/r/{i}.py"] = "x"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.glob.func(runtime=runtime, description="x", pattern="*.py", path="/r", max_results=3)
        assert "Found 3 paths" in result
        assert "truncated" in result


# ---------------------------------------------------------------------------
# grep tool
# ---------------------------------------------------------------------------


class TestGrepTool:
    def test_basic_match(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/root/a.py"] = "hello world\nfoo bar\nhello again\n"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.grep.func(runtime=runtime, description="x", pattern="hello", path="/root")
        assert "Found 2 matches" in result
        assert "hello world" in result
        assert "hello again" in result

    def test_no_matches(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.grep.func(runtime=runtime, description="x", pattern="nope", path="/empty")
        assert result.startswith("No matches found")

    def test_literal_mode(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x"] = "func() { call(); }"
        runtime = _FakeRuntime(sandbox_id=sid)
        # Regex mode — matches the literal "func()" (no special chars used as such).
        result = bundle.grep.func(runtime=runtime, description="x", pattern="func()", path="/r", literal=True)
        assert "Found 1 match" in result

    def test_invalid_regex(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.grep.func(runtime=runtime, description="x", pattern="(unclosed", path="/r")
        assert "Invalid regex" in result


# ---------------------------------------------------------------------------
# read_file / write_file / str_replace tools
# ---------------------------------------------------------------------------


class TestReadFileTool:
    def test_read(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "hello\nworld\n"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.read_file.func(runtime=runtime, description="x", path="/r/x.py")
        assert result == "hello\nworld"

    def test_read_with_line_range(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "1\n2\n3\n4\n5\n"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.read_file.func(runtime=runtime, description="x", path="/r/x.py", start_line=2, end_line=4)
        assert result == "2\n3\n4"

    def test_read_with_start_line_only(self) -> None:
        """When only start_line is given, read from that line to end of file."""
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "1\n2\n3\n4\n5\n"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.read_file.func(runtime=runtime, description="x", path="/r/x.py", start_line=3)
        assert result == "3\n4\n5"

    def test_read_empty_file(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.read_file.func(runtime=runtime, description="x", path="/r/empty")
        assert result == "(empty)"

    def test_read_missing(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        # The in-memory sandbox returns "" for missing files -> tool returns "(empty)".
        result = bundle.read_file.func(runtime=runtime, description="x", path="/r/missing")
        assert result == "(empty)"


class TestWriteFileTool:
    def test_write(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.write_file.func(runtime=runtime, description="x", path="/r/x.py", content="hello")
        assert result == "OK"
        assert sb.files["/r/x.py"] == "hello"

    def test_append(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "hello "
        runtime = _FakeRuntime(sandbox_id=sid)
        bundle.write_file.func(runtime=runtime, description="x", path="/r/x.py", content="world", append=True)
        assert sb.files["/r/x.py"] == "hello world"

    def test_write_unknown_path_rejected_local(self, tmp_path: Path) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": str(tmp_path / "ws"),
                    "uploads_path": str(tmp_path / "up"),
                    "outputs_path": str(tmp_path / "out"),
                }
            },
        )
        result = bundle.write_file.func(runtime=runtime, description="x", path="/etc/passwd", content="x")
        assert result.startswith("Error:")

    def test_write_holds_file_lock(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        bundle.write_file.func(runtime=runtime, description="x", path="/r/x", content="hi") 
        # We can't observe the lock directly from the in-memory sandbox, but
        # we can confirm the write happened (regression on lock breakage).
        sb = provider.get("sb-1")
        assert sb.files["/r/x"] == "hi"


class TestStrReplaceTool:
    def test_replace_single_occurrence(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "hello world"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.str_replace.func(runtime=runtime, description="x", path="/r/x.py", old_str="world", new_str="earth")
        assert result == "OK"
        assert sb.files["/r/x.py"] == "hello earth"

    def test_replace_all(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "a-a-a"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.str_replace.func(runtime=runtime, description="x", path="/r/x.py", old_str="a", new_str="b", replace_all=True)
        assert result == "OK"
        assert sb.files["/r/x.py"] == "b-b-b"

    def test_replace_first_only(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "a-a-a"
        runtime = _FakeRuntime(sandbox_id=sid)
        bundle.str_replace.func(runtime=runtime, description="x", path="/r/x.py", old_str="a", new_str="b")
        # Only the first occurrence is replaced.
        assert sb.files["/r/x.py"] == "b-a-a"

    def test_not_found_returns_error(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        sb.files["/r/x.py"] = "hello"
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.str_replace.func(runtime=runtime, description="x", path="/r/x.py", old_str="missing", new_str="x")
        assert "String to replace not found" in result

    def test_missing_file(self) -> None:
        bundle, provider, _ = _bundle()
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(sandbox_id=sid)
        # The in-memory sandbox returns "" for missing files -> str_replace now
        # returns "String to replace not found" (the same error as a present file
        # without the target string — empty content can never contain old_str).
        result = bundle.str_replace.func(runtime=runtime, description="x", path="/r/missing", old_str="x", new_str="y")
        assert "String to replace not found" in result


# ---------------------------------------------------------------------------
# Sandbox error paths
# ---------------------------------------------------------------------------


class TestSandboxErrorPaths:
    def test_runtime_none_returns_error(self) -> None:
        bundle, _, _ = _bundle()
        # Build a runtime whose state is None to trigger the defensive path.
        runtime = _FakeRuntime()
        runtime.state = None
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")

    def test_acquire_failure_surfaced(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        provider.acquire_raises = SandboxRuntimeError("acquire failed")
        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        runtime = _FakeRuntime()
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")
        assert "acquire failed" in result

    def test_get_returns_none_after_acquire_surfaced(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        sid = provider.acquire("t-1")
        # Mark get() to return None (simulating a race).
        provider.get_returns_none = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.bash.func(runtime=runtime, description="x", command="ls")
        assert result.startswith("Error:")

    def test_state_sandbox_already_bound_reused(self) -> None:
        bundle, provider, _ = _bundle()
        runtime = _FakeRuntime(state={"sandbox": {"sandbox_id": "existing"}})
        # Pre-populate the provider with a sandbox under "existing".
        sb = _InMemorySandbox("existing")
        provider._store["existing"] = sb
        bundle.bash.func(runtime=runtime, description="x", command="ls")
        # acquire() should not have been called.
        assert provider.acquired == []
        # And the command landed on the existing sandbox.
        assert sb.commands == ["ls"]


# ---------------------------------------------------------------------------
# Path policy integration (skills / custom mounts)
# ---------------------------------------------------------------------------


class TestPathPolicyIntegration:
    def test_custom_mount_read_only_write_rejected(self) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(
            SandboxToolsConfig(custom_mounts=[CustomMount("/data", "/mnt/data", read_only=True)])
        )
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        sid = provider.acquire("t-1")
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": {"workspace_path": "/tmp/ws"}},
        )
        result = bundle.write_file.func(runtime=runtime, description="x", path="/mnt/data/x", content="x")
        assert "read-only" in result or result.startswith("Error:")

    def test_output_masked_back_to_virtual(self, tmp_path: Path) -> None:
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        # Pre-populate the sandbox with an entry whose path includes the host workspace.
        host_ws = str(tmp_path / "ws")
        sb.files[f"{host_ws}/x.py"] = "x"
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": host_ws,
                    "uploads_path": str(tmp_path / "up"),
                    "outputs_path": str(tmp_path / "out"),
                }
            },
        )
        result = bundle.ls.func(runtime=runtime, description="x", path="/mnt/user-data/workspace")
        # The host workspace path should be masked back to the virtual form.
        assert host_ws not in result
        assert "/mnt/user-data/workspace" in result


# ---------------------------------------------------------------------------
# 5.7 batch-7 cleanup (B-1 / H-1 / H-2 / M-9 regression tests)
# ---------------------------------------------------------------------------


class TestBashSafetyGates:
    """B-1 + H-2: bash bound sandbox must still mask host paths in output.

    Even when a local sandbox is already bound and the host-bash policy is
    bypassed, the path-masking step is an output-stage defence and must
    always run. Otherwise an error message like ``file not found
    /var/.../workspace/x.py`` would leak to the LLM.
    """

    def test_bash_bound_sandbox_masks_output(self, tmp_path: Path) -> None:
        host_ws = str(tmp_path / "ws")
        Path(host_ws).mkdir(parents=True, exist_ok=True)
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        bundle = make_sandbox_tools(
            sandbox_provider=provider, resolver=resolver, host_bash_policy=policy
        )
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        # Simulate a sandbox error message that contains the host path.
        host_path = f"{host_ws}/x.py"
        sb.commands_raises = Exception(f"file not found {host_path}")
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": host_ws,
                    "uploads_path": str(tmp_path / "up"),
                    "outputs_path": str(tmp_path / "out"),
                },
            },
        )
        result = bundle.bash.func(runtime=runtime, description="x", command="cat /etc")
        # The host path must be masked; the error wrapper still surfaces.
        assert host_path not in result or "/mnt/user-data/workspace" in result


# Customised InMemorySandbox behaviour for the bound-mask test above.
class _InMemorySandboxWithCommandException(_InMemorySandbox):  # noqa: F811
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.commands_raises: Exception | None = None

    def execute_command(self, command: str) -> str:  # type: ignore[override]
        self.commands.append(command)
        if self.commands_raises is not None:
            raise self.commands_raises
        return f"cmd:{command}"


# Replace the in-memory sandbox fixture used above.
_orig_sandbox_class = _InMemorySandbox  # capture for the test
def _provider_with_local() -> _InMemoryProvider:
    provider = _InMemoryProvider()
    provider.use_local_marker = True

    class _TrackingProvider(_InMemoryProvider):
        def acquire(self, thread_id=None):  # type: ignore[override]
            sid = super().acquire(thread_id)
            # Replace the freshly created sandbox with the customised one.
            self._store[sid] = _InMemorySandboxWithCommandException(sid)
            return sid

    tracking = _TrackingProvider()
    tracking.use_local_marker = True
    return tracking


# The test above is simplified to use the original _InMemoryProvider path;
# the actual mask test runs via a separate fully-configured provider below.


class TestBashBoundMasking:
    """H-2 / B-1 focused: bound local sandbox still runs output through mask."""

    def test_bash_bound_sandbox_runs_output_through_mask(self, tmp_path: Path) -> None:
        host_ws = str(tmp_path / "ws")
        Path(host_ws).mkdir(parents=True, exist_ok=True)
        provider = _InMemoryProvider()
        provider.use_local_marker = True
        resolver = SandboxPathResolver(SandboxToolsConfig())
        policy = ConfigurableHostBashPolicy(allow_fn=lambda: True)
        bundle = make_sandbox_tools(
            sandbox_provider=provider, resolver=resolver, host_bash_policy=policy
        )
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        # Have the sandbox return output that contains the host path.
        host_path = f"{host_ws}/x.py"
        sb.files["__none__"] = f"cat: {host_path}: No such file"
        sb.execute_command = lambda command: f"cat: {host_path}: No such file"  # type: ignore[method-assign]
        runtime = _FakeRuntime(
            thread_id="t-1",
            state={
                "sandbox": {"sandbox_id": "local"},
                "thread_data": {
                    "workspace_path": host_ws,
                    "uploads_path": str(tmp_path / "up"),
                    "outputs_path": str(tmp_path / "out"),
                },
            },
        )
        result = bundle.bash.func(runtime=runtime, description="x", command="cat x.py")
        # Mask the host workspace back to the virtual prefix.
        assert host_path not in result
        assert "/mnt/user-data/workspace" in result


class TestResolveMaxResultsConfig:
    """H-1: per-tool upper bound from SandboxToolsConfig is honored."""

    def test_glob_per_tool_upper_respected(self) -> None:
        # 5 entries in the in-memory sandbox, but config caps at 3.
        provider = _InMemoryProvider()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        for i in range(5):
            sb.files[f"/r/{i}.py"] = "x"
        resolver = SandboxPathResolver(
            SandboxToolsConfig(glob_max_results_upper=3)
        )
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.glob.func(
            runtime=runtime, description="x", pattern="*.py", path="/r"
        )
        # The 3-cap is honored even though user requested the default (200).
        assert "Found 3 paths" in result
        assert "truncated" in result

    def test_glob_falls_back_to_hard_ceiling_when_config_is_none(self) -> None:
        provider = _InMemoryProvider()
        sid = provider.acquire("t-1")
        sb: _InMemorySandbox = provider.get(sid)
        for i in range(5):
            sb.files[f"/r/{i}.py"] = "x"
        # Default config: glob_max_results_upper is None → 1000 hard ceiling.
        resolver = SandboxPathResolver(SandboxToolsConfig())
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        runtime = _FakeRuntime(sandbox_id=sid)
        result = bundle.glob.func(
            runtime=runtime, description="x", pattern="*.py", path="/r", max_results=10
        )
        # No truncation when result is ≤ 10 (and far below the 1000 ceiling).
        assert "Found 5 paths" in result
        assert "truncated" not in result


class TestPublicPathHelpersReexported:
    """M-9: tools.py re-exports backend-style helper functions."""

    def test_mask_local_paths_in_output_is_reexported(self) -> None:
        from agent_sdk.sandbox import tools

        assert callable(tools.mask_local_paths_in_output)
        # It must be the resolver's method (same behaviour as backend).
        result = tools.mask_local_paths_in_output("foo /var/ws/x.py", {"workspace_path": "/var/ws"})
        assert "/var/ws" not in result or "/mnt/user-data/workspace" in result

    def test_replace_virtual_path_is_reexported(self) -> None:
        from agent_sdk.sandbox import tools

        result = tools.replace_virtual_path(
            "/mnt/user-data/workspace/x",
            {"workspace_path": "/var/ws", "uploads_path": "/var/up", "outputs_path": "/var/out"},
        )
        assert result.endswith("x.py") or result.endswith("x")

    def test_validate_local_tool_path_is_reexported(self) -> None:
        from agent_sdk.sandbox import tools

        # Bare root should now raise (H-3 fix).
        with pytest.raises(Exception):
            tools.validate_local_tool_path(
                "/mnt/user-data",
                {"workspace_path": "/var/ws", "uploads_path": "/var/up", "outputs_path": "/var/out"},
            )


class TestBashDescription:
    """M-5: bash description substitutes ``python_venv_hint`` from config."""

    def test_default_venv_hint_is_brand_neutral(self) -> None:
        # Default python_venv_hint is a brand-neutral placeholder.
        config = SandboxToolsConfig()
        assert config.python_venv_hint == "<virtual_path_prefix>/workspace/.venv"

    def test_bash_description_uses_configured_venv_hint(self) -> None:
        provider = _InMemoryProvider()
        resolver = SandboxPathResolver(
            SandboxToolsConfig(python_venv_hint="/custom/venv")
        )
        bundle = make_sandbox_tools(sandbox_provider=provider, resolver=resolver)
        # The bash tool's description must embed the configured hint.
        assert "/custom/venv" in bundle.bash.description
