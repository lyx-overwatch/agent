"""Sandbox and SandboxProvider abstract base classes.

This module is a re-implementation (per ADR-010) of the sandbox
contracts. The shape mirrors the original
``deerflow.sandbox.Sandbox`` / ``deerflow.sandbox.SandboxProvider``
so that any concrete backend (local shell, AIO sandbox, k8s pod,
Docker container) can plug in, but the SDK version:

* does not import from ``deerflow.*`` / ``backend.*`` / ``app.*``;
* does not depend on ``deerflow.config`` or ``deerflow.reflection``;
* does not maintain a process-wide singleton — providers are
  constructed and injected explicitly by the caller (typically
  :class:`agent_sdk.runtime.RunManager` or a user setup function).

The provider is intentionally minimal: ``acquire`` / ``get`` /
``release``.  A concrete provider is expected to manage its own
resource pool (e.g. a process pool, a Docker daemon connection, a
remote sandbox broker) and decide how to map ``thread_id`` to a
concrete sandbox instance.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class GrepMatch:
    """A single regex match inside a sandbox file.

    Attributes:
        path: Absolute physical path of the file that contained the
            match. The path is in the host filesystem (post-virtual
            translation, if any).
        line_number: 1-based line number of the match.
        line: The matched line text. Implementations are expected to
            truncate long lines (the SDK's in-tree search helper
            uses 200 characters by default).
    """

    path: str
    line_number: int
    line: str


class Sandbox(abc.ABC):
    """Abstract base class for a single sandbox instance.

    A :class:`Sandbox` is a long-lived execution environment for a
    single agent thread. It exposes the I/O primitives the runtime
    needs to back the file/bash tools.

    Lifecycle:
        A sandbox is created by :meth:`SandboxProvider.acquire`,
        identified by a string ``id`` (immutable for the lifetime
        of the instance), and released by
        :meth:`SandboxProvider.release`. Implementations are
        expected to free any per-instance resources (open files,
        subprocesses, temp dirs) on release.
    """

    _id: str

    def __init__(self, id: str) -> None:
        self._id = id

    @property
    def id(self) -> str:
        """Return the immutable sandbox identifier."""
        return self._id

    @abc.abstractmethod
    def execute_command(self, command: str) -> str:
        """Execute a bash command in the sandbox.

        Args:
            command: The command to execute. Implementations decide
                whether to run on the host, in a container, or via
                a remote broker.

        Returns:
            Combined standard or error output of the command as a
            single string. The format is implementation-defined
            but must be suitable for inclusion in a tool result.
        """

    @abc.abstractmethod
    def read_file(self, path: str) -> str:
        """Read the UTF-8 contents of a file at *path*.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The file contents decoded as text. Implementations
            should pick a deterministic encoding (the in-tree
            reference uses ``utf-8`` with ``errors="replace"``).
        """

    @abc.abstractmethod
    def read_file_bytes(self, path: str) -> bytes:
        """Read the raw bytes of a file at *path*.

        Unlike :meth:`read_file`, this performs no text decoding
        and is the correct way to pull binary files (images, docx,
        xlsx, pdf) out of the sandbox without corruption.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The raw file bytes. Implementations should raise
            ``FileNotFoundError`` when the file does not exist.
        """

    @abc.abstractmethod
    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        """List the entries under *path*.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. The default
                (``2``) matches the in-tree reference. The semantics
                of "depth 0" / "depth 1" are implementation-defined
                but should be self-consistent with the runtime's
                agent-facing tool description.

        Returns:
            A list of paths, in the order produced by the
            implementation. No sorting is guaranteed.
        """

    @abc.abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write text content to a file.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write.
            append: If ``True``, append to the existing file;
                otherwise overwrite. Implementations are expected
                to create the file (and any missing parent
                directories) if it does not exist.
        """

    @abc.abstractmethod
    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        """Find paths matching a glob pattern under *path*.

        Args:
            path: Absolute path of the root directory to search.
            pattern: Glob pattern (POSIX or implementation-native).
            include_dirs: Whether to include directories in the
                result. The default (``False``) returns files only.
            max_results: Upper bound on returned paths. Returns
                ``True`` as the second tuple element when the
                result was truncated at this bound.

        Returns:
            A tuple ``(matches, truncated)`` where ``matches`` is
            the list of absolute paths that matched and
            ``truncated`` is ``True`` if the result was cut at
            ``max_results``.
        """

    @abc.abstractmethod
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
        """Search for *pattern* in text files under *path*.

        Args:
            path: Absolute path of the root directory to search.
            pattern: Regex source (``literal=False``) or literal
                substring (``literal=True``).
            glob: Optional secondary glob filter applied to each
                file's relative path.
            literal: If ``True``, treat *pattern* as a literal
                substring; if ``False`` (default), treat as a regex.
            case_sensitive: If ``False`` (default), search is
                case-insensitive.
            max_results: Upper bound on returned matches. The
                second tuple element is ``True`` when truncated.

        Returns:
            A tuple ``(matches, truncated)`` where ``matches`` is
            a list of :class:`GrepMatch` instances and
            ``truncated`` indicates overflow at ``max_results``.
        """

    @abc.abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content.

        Args:
            path: The absolute path of the file to update.
            content: The raw bytes to write. The file is
                created or overwritten (no partial edits; this
                is distinct from the text-mode
                :meth:`write_file`).
        """


class SandboxProvider(abc.ABC):
    """Abstract base class for sandbox pool providers.

    A provider owns the lifecycle of one or more :class:`Sandbox`
    instances. The runtime calls :meth:`acquire` to obtain a
    sandbox for a thread, :meth:`get` to look up an existing one
    by id, and :meth:`release` to free resources when the thread
    ends.

    Class attributes:
        uses_thread_data_mounts: Whether the provider's sandboxes
            expose the runtime's per-thread data directory (e.g.
            workspace / uploads / outputs) as a mount. Runtimes
            that virtualize paths use this to decide whether to
            apply :class:`agent_sdk.paths.resolver.VirtualPathResolver`
            before talking to the sandbox. The default ``False``
            matches a host-side implementation; container/remote
            providers that need explicit mounts should set
            ``True``.
    """

    uses_thread_data_mounts: bool = False

    @abc.abstractmethod
    def acquire(self, thread_id: str | None = None) -> str:
        """Acquire a sandbox for *thread_id* and return its id.

        Args:
            thread_id: Optional identifier of the calling thread.
                Implementations may use this to bind a sandbox to
                a thread (e.g. for path mapping, telemetry, or
                quota tracking) or to ignore it.

        Returns:
            The id of the acquired sandbox. The id is opaque to
            the runtime and is only meaningful when passed back
            to :meth:`get` / :meth:`release`.
        """

    @abc.abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """Look up an existing sandbox by id.

        Args:
            sandbox_id: The id returned by a prior
                :meth:`acquire` call.

        Returns:
            The :class:`Sandbox` instance, or ``None`` if the id
            is unknown (e.g. it was already released or the
            provider has been re-initialised).
        """

    @abc.abstractmethod
    def release(self, sandbox_id: str) -> None:
        """Release a sandbox.

        Args:
            sandbox_id: The id of the sandbox to destroy. After
                this call :meth:`get` will return ``None`` for
                the same id. Implementations must free any
                per-sandbox resources (subprocesses, mounts,
                temp dirs).
        """

    def shutdown(self) -> None:
        """Release all resources held by the provider.

        Optional. The default is a no-op for stateless
        providers. Implementations that own a process pool,
        a long-lived container, or a remote connection should
        override this to ensure clean shutdown.
        """
