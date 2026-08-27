"""AioSandbox — wraps the agent_sandbox client library to implement the agent_sdk Sandbox ABC.

Connects to a running AIO sandbox Docker container via its HTTP API.
A threading lock serialises shell commands to prevent concurrent
requests from corrupting the container's persistent shell session.
"""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import shlex
import threading
import uuid

from agent_sdk.sandbox.base import GrepMatch, Sandbox
from agent_sdk.sandbox.search import (
    path_matches,
    should_ignore_path,
    truncate_line,
)

logger = logging.getLogger(__name__)

_ERROR_OBSERVATION_SIGNATURE = "'ErrorObservation' object has no attribute 'exit_code'"

#: Per-operation deadline for Docker sandbox file operations (glob, grep,
#: list_dir, read_file).  The underlying HTTP client has a 600 s ceiling,
#: but individual tool calls should time out much sooner so the agent can
#: retry or switch strategies.
_AIO_TOOL_DEADLINE_SEC = 60.0


class AioSandbox(Sandbox):
    """Sandbox implementation backed by an AIO sandbox Docker container.

    Connects to a running AIO sandbox container via the ``agent_sandbox``
    client library.  A threading lock serialises shell commands to
    prevent concurrent requests from corrupting the container's
    persistent shell session.
    """

    def __init__(self, id: str, base_url: str, home_dir: str | None = None):
        super().__init__(id)
        try:
            from agent_sandbox import Sandbox as AioSandboxClient
        except ImportError as exc:
            raise ImportError(
                "agent-sandbox is required for AioSandbox. "
                "Install it with: uv add agent-sandbox"
            ) from exc
        self._base_url = base_url
        self._client = AioSandboxClient(base_url=base_url, timeout=600)
        self._home_dir = home_dir
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def home_dir(self) -> str:
        if self._home_dir is None:
            context = self._client.sandbox.get_context()
            self._home_dir = context.home_dir
        return self._home_dir

    # ── Deadline helper ────────────────────────────────────────────────

    @staticmethod
    def _run_with_deadline(fn, deadline: float, error_prefix: str = "") -> object:
        """Run *fn* in a thread and return its result, or a timeout error string.

        The underlying HTTP client has a 600 s ceiling, but individual
        tool calls time out at *deadline* seconds so the agent can
        retry or switch strategies instead of blocking the conversation
        for minutes.
        """
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(fn)
                return future.result(timeout=deadline)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "%soperation timed out after %.0fs", error_prefix, deadline
            )
            return f"Error: {error_prefix}operation timed out after {deadline:.0f}s"
        except Exception as exc:
            logger.error("%soperation failed: %s", error_prefix, exc)
            return f"Error: {error_prefix}{exc}"

    # ── Sandbox ABC ──────────────────────────────────────────────────

    def execute_command(self, command: str) -> str:
        with self._lock:
            try:
                result = self._client.shell.exec_command(command=command)
                output = result.data.output if result.data else ""

                if output and _ERROR_OBSERVATION_SIGNATURE in output:
                    logger.warning(
                        "ErrorObservation detected in sandbox output, "
                        "retrying with a fresh session"
                    )
                    fresh_id = str(uuid.uuid4())
                    result = self._client.shell.exec_command(command=command, id=fresh_id)
                    output = result.data.output if result.data else ""

                return output if output else "(no output)"
            except Exception as e:
                logger.error(f"Failed to execute command in sandbox: {e}")
                return f"Error: {e}"

    def read_file(self, path: str) -> str:
        def _read() -> str:
            result = self._client.file.read_file(file=path)
            return result.data.content if result.data else ""

        raw = self._run_with_deadline(_read, _AIO_TOOL_DEADLINE_SEC, error_prefix="read_file ")
        if isinstance(raw, str) and raw.startswith("Error:"):
            return raw
        return raw

    def read_file_bytes(self, path: str) -> bytes:
        return self.download_file_bytes(path)

    def download_file_bytes(self, path: str) -> bytes:
        """Read a file as raw bytes via the sandbox's streaming download API.

        Uses the ``v1/file/download`` FileResponse endpoint, which streams
        the file's raw bytes directly.  This is the only reliable way to
        pull binary deliverables (docx, xlsx, pdf, images) out of the
        sandbox without corruption.

        The previous approach — ``base64 -w0`` through ``execute_command``
        — was silently truncated by the shell API, which caps command
        output at 30000 characters by default (``truncate=True``).  Any
        file larger than ~22 KiB therefore came back truncated, and
        :func:`base64.b64decode` either raised or produced a corrupt
        partial file.
        """
        try:
            return b"".join(self._client.file.download_file(path=path))
        except Exception as exc:
            logger.warning("download_file_bytes(%s) failed: %s", path, exc)
            return b""

    def list_files(self, path: str, *, max_depth: int | None = None) -> list[str]:
        """Recursively list files under *path* in the sandbox.

        Args:
            path: Absolute sandbox path to list.
            max_depth: Maximum directory depth (``None`` = unlimited).

        Returns:
            List of absolute file paths (directories excluded).
        """
        try:
            result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
            entries = result.data.files if result.data and result.data.files else []
            root = path.rstrip("/")
            files: list[str] = []
            for entry in entries:
                if entry.is_directory:
                    continue
                entry_path = entry.path
                if max_depth is not None:
                    rel = entry_path.removeprefix(root).lstrip("/")
                    depth = rel.count("/") + 1 if rel else 0
                    if depth > max_depth:
                        continue
                files.append(entry_path)
            return files
        except Exception as exc:
            logger.error("list_files(%s) failed: %s", path, exc)
            return []

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        def _list() -> list[str]:
            with self._lock:
                result = self._client.shell.exec_command(
                    command=(
                        f"find {shlex.quote(path)} -maxdepth {max_depth} "
                        f"-type f -o -type d 2>/dev/null | head -500"
                    )
                )
                output = result.data.output if result.data else ""
                if output:
                    return [line.strip() for line in output.strip().split("\n") if line.strip()]
                return []

        raw = self._run_with_deadline(_list, _AIO_TOOL_DEADLINE_SEC, error_prefix="list_dir ")
        if isinstance(raw, str) and raw.startswith("Error:"):
            return []
        return raw

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        with self._lock:
            try:
                if append:
                    existing = self.read_file(path)
                    if not existing.startswith("Error:"):
                        content = existing + content
                self._client.file.write_file(file=path, content=content)
            except Exception as e:
                logger.error(f"Failed to write file in sandbox: {e}")
                raise

    def glob(
        self, path: str, pattern: str, *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        def _glob() -> tuple[list[str], bool]:
            if not include_dirs:
                result = self._client.file.find_files(path=path, glob=pattern)
                files = result.data.files if result.data and result.data.files else []
                filtered = [file_path for file_path in files if not should_ignore_path(file_path)]
                truncated = len(filtered) > max_results
                return filtered[:max_results], truncated

            result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
            entries = result.data.files if result.data and result.data.files else []
            matches: list[str] = []
            root_path = path.rstrip("/") or "/"
            root_prefix = root_path if root_path == "/" else f"{root_path}/"
            for entry in entries:
                if entry.path != root_path and not entry.path.startswith(root_prefix):
                    continue
                if should_ignore_path(entry.path):
                    continue
                rel_path = entry.path[len(root_path):].lstrip("/")
                if path_matches(pattern, rel_path):
                    matches.append(entry.path)
                    if len(matches) >= max_results:
                        return matches, True
            return matches, False

        raw = self._run_with_deadline(_glob, _AIO_TOOL_DEADLINE_SEC, error_prefix="glob ")
        if isinstance(raw, str) and raw.startswith("Error:"):
            return [], False
        return raw

    def grep(
        self, path: str, pattern: str, *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        import re as _re

        regex_source = _re.escape(pattern) if literal else pattern
        _re.compile(regex_source, 0 if case_sensitive else _re.IGNORECASE)
        regex = regex_source if case_sensitive else f"(?i){regex_source}"

        def _grep() -> tuple[list[GrepMatch], bool]:
            if glob is not None:
                find_result = self._client.file.find_files(path=path, glob=glob)
                candidate_paths = (
                    find_result.data.files
                    if find_result.data and find_result.data.files
                    else []
                )
            else:
                list_result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
                entries = list_result.data.files if list_result.data and list_result.data.files else []
                candidate_paths = [entry.path for entry in entries if not entry.is_directory]

            matches: list[GrepMatch] = []
            truncated = False

            for file_path in candidate_paths:
                if should_ignore_path(file_path):
                    continue
                search_result = self._client.file.search_in_file(file=file_path, regex=regex)
                data = search_result.data
                if data is None:
                    continue
                line_numbers = data.line_numbers or []
                matched_lines = data.matches or []
                for line_number, line in zip(line_numbers, matched_lines):
                    matches.append(
                        GrepMatch(
                            path=file_path,
                            line_number=line_number if isinstance(line_number, int) else 0,
                            line=truncate_line(line),
                        )
                    )
                    if len(matches) >= max_results:
                        truncated = True
                        return matches, truncated

            return matches, truncated

        raw = self._run_with_deadline(_grep, _AIO_TOOL_DEADLINE_SEC, error_prefix="grep ")
        if isinstance(raw, str) and raw.startswith("Error:"):
            return [], False
        return raw

    def update_file(self, path: str, content: bytes) -> None:
        with self._lock:
            try:
                b64_content = base64.b64encode(content).decode("utf-8")
                self._client.file.write_file(file=path, content=b64_content, encoding="base64")
            except Exception as e:
                logger.error(f"Failed to update file in sandbox: {e}")
                raise