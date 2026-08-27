"""Local subprocess-based sandbox provider.

:class:`LocalSandboxProvider` — a minimal implementation of the
agent_sdk ``SandboxProvider`` / ``Sandbox`` ABCs backed by Python
``subprocess``.  **Not safe for production** — the agent can access
any file on the host.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import time
from pathlib import Path

from agent_sdk.sandbox.base import GrepMatch, Sandbox, SandboxProvider

_MAX_OUTPUT = 50_000

#: Maximum filesystem entries to traverse in a single ``os.walk`` call
#: (glob / ls / grep).  Prevents infinite walks on deep or cyclic directory
#: trees (especially on Windows where ``followlinks`` may create cycles).
_MAX_WALK_ENTRIES = 100_000

#: Maximum size (bytes) of a file that ``grep`` will open.  Files larger
#: than this are skipped with a note in the results.
_MAX_GREP_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB

#: Per-operation deadline for blocking I/O tools (glob / ls / grep /
#: read_file).  If an ``os.walk`` or file read exceeds this wall-clock
#: duration the tool returns partial results with a timeout marker.
_TOOL_DEADLINE_SEC = 60.0


class LocalSandbox(Sandbox):
    """A single-thread sandbox that runs commands via subprocess."""

    def __init__(self, id: str, workspace: Path) -> None:
        super().__init__(id)
        self._workspace = workspace.resolve()

    @staticmethod
    def _deadline_exceeded(deadline: float) -> bool:
        """Return ``True`` when *deadline* (from ``time.monotonic()``) has passed."""
        return time.monotonic() >= deadline

    def _guard(self, path: Path) -> None:
        """Reject writes outside the sandbox workspace root."""
        try:
            path.resolve().relative_to(self._workspace)
        except ValueError:
            raise PermissionError(
                f"Access denied: {path} is outside sandbox workspace {self._workspace}"
            )

    def execute_command(self, command: str) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self._workspace,
            )
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            return output[:_MAX_OUTPUT] or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30s"
        except Exception as e:
            return f"Error: {e}"

    def read_file(self, path: str) -> str:
        try:
            fp = Path(path)
            if not fp.is_absolute():
                fp = self._workspace / path
            return fp.read_text(encoding="utf-8", errors="replace")[:_MAX_OUTPUT]
        except FileNotFoundError:
            return f"Error: File not found: {path}"
        except PermissionError as e:
            return f"Error: Permission denied: {e}"
        except TimeoutError:
            return "Error: File read timed out"
        except Exception as e:
            return f"Error: {e}"

    def read_file_bytes(self, path: str) -> bytes:
        fp = Path(path)
        if not fp.is_absolute():
            fp = self._workspace / path
        return fp.read_bytes()

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        results: list[str] = []
        deadline = time.monotonic() + _TOOL_DEADLINE_SEC
        entries_seen = 0
        try:
            fp = Path(path)
            if not fp.is_absolute():
                fp = self._workspace / path
            if not fp.exists():
                return []
            for root, dirs, files in os.walk(fp):
                entries_seen += len(dirs) + len(files)
                if entries_seen > _MAX_WALK_ENTRIES:
                    results.append(f"[stopped: exceeded {_MAX_WALK_ENTRIES} entries]")
                    return results
                if self._deadline_exceeded(deadline):
                    results.append(f"[stopped: timeout after {_TOOL_DEADLINE_SEC:.0f}s]")
                    return results
                depth = len(Path(root).relative_to(fp).parts)
                if depth >= max_depth:
                    dirs.clear()
                for name in files:
                    results.append(str(Path(root) / name))
            return results
        except Exception:
            return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        fp = Path(path)
        if not fp.is_absolute():
            fp = self._workspace / path
        self._guard(fp)
        fp.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with fp.open("a") as f:
                f.write(content)
        else:
            fp.write_text(content, encoding="utf-8")

    def glob(
        self, path: str, pattern: str, *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        results: list[str] = []
        deadline = time.monotonic() + _TOOL_DEADLINE_SEC
        entries_seen = 0
        try:
            fp = Path(path)
            if not fp.is_absolute():
                fp = self._workspace / path
            if not fp.exists():
                return [], False
            for root, dirs, files in os.walk(fp):
                entries_seen += len(dirs) + len(files)
                if entries_seen > _MAX_WALK_ENTRIES:
                    results.append(f"[stopped: exceeded {_MAX_WALK_ENTRIES} entries under {path}]")
                    return results, True
                if self._deadline_exceeded(deadline):
                    results.append(f"[stopped: timeout after {_TOOL_DEADLINE_SEC:.0f}s]")
                    return results, True
                for name in dirs if include_dirs else []:
                    if fnmatch.fnmatch(name, pattern):
                        results.append(str(Path(root) / name))
                        if len(results) >= max_results:
                            return results, True
                for name in files:
                    if fnmatch.fnmatch(name, pattern):
                        results.append(str(Path(root) / name))
                        if len(results) >= max_results:
                            return results, True
            return results, False
        except Exception:
            return [], False

    def grep(
        self, path: str, pattern: str, *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        results: list[GrepMatch] = []
        deadline = time.monotonic() + _TOOL_DEADLINE_SEC
        entries_seen = 0
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(re.escape(pattern) if literal else pattern, flags)
            fp = Path(path)
            if not fp.is_absolute():
                fp = self._workspace / path
            if not fp.exists():
                return [], False
            for root, _dirs, files in os.walk(fp):
                entries_seen += len(files)
                if entries_seen > _MAX_WALK_ENTRIES:
                    return results, True
                if self._deadline_exceeded(deadline):
                    return results, True
                for name in files:
                    if glob and not fnmatch.fnmatch(name, glob):
                        continue
                    file_path = Path(root) / name
                    try:
                        if file_path.stat().st_size > _MAX_GREP_FILE_SIZE:
                            continue
                    except OSError:
                        continue
                    try:
                        for i, line in enumerate(file_path.read_text(errors="replace").splitlines(), 1):
                            if regex.search(line):
                                results.append(GrepMatch(path=str(file_path), line_number=i, line=line[:200]))
                                if len(results) >= max_results:
                                    return results, True
                    except Exception:
                        continue
            return results, False
        except Exception:
            return [], False

    def update_file(self, path: str, content: bytes) -> None:
        fp = Path(path)
        if not fp.is_absolute():
            fp = self._workspace / path
        self._guard(fp)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(content)


class LocalSandboxProvider(SandboxProvider):
    """A simple in-process sandbox provider backed by subprocess.

    Creates one :class:`LocalSandbox` per thread, keyed by thread_id.
    """

    uses_thread_data_mounts: bool = False

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, LocalSandbox] = {}

    def acquire(self, thread_id: str | None = None) -> str:
        from agent_sdk.runtime.user_context import get_effective_user_id

        sid = thread_id or f"local_{id(self)}"
        if sid not in self._sandboxes:
            if thread_id:
                user_id = get_effective_user_id()
                thread_dir = self._workspace / "users" / (user_id or "default") / "threads" / sid
                ws = thread_dir / "workspace"
                (thread_dir / "uploads").mkdir(parents=True, exist_ok=True)
                (thread_dir / "outputs").mkdir(parents=True, exist_ok=True)
            else:
                ws = self._workspace
            ws.mkdir(parents=True, exist_ok=True)
            self._sandboxes[sid] = LocalSandbox(sid, ws)
        return sid

    def get(self, sandbox_id: str) -> Sandbox | None:
        return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)

    def shutdown(self) -> None:
        self._sandboxes.clear()