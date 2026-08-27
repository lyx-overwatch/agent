"""PathProvider Protocol.

A :class:`PathProvider` is the brand-neutral injection point for runtime
path configuration. All methods MUST return absolute physical paths
(``pathlib.Path``); virtual-to-physical translation is handled by
:class:`agent_sdk.paths.resolver.VirtualPathResolver`.

Implementations are typically stateless apart from a base directory
configuration. Threading a single provider instance through the runtime
is expected; methods may be called concurrently.

This Protocol follows ADR-001 (feature-rich + brand-neutral) and
ADR-010 (re-implementation, no code-mover): the SDK never hard-codes
any product-specific path prefix. The DeerFlow preset's
:class:`DeerFlowPathProvider` lives in
``agent_sdk.presets.deerflow.paths`` and preserves the
``/mnt/user-data`` behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PathProvider(Protocol):
    """Provides filesystem path resolution for a runtime.

    All paths returned MUST be absolute physical paths. The provider is
    the single source of truth for "where does the runtime store X?".

    Threading and lifetime:
        A single instance is expected to be created at agent setup and
        shared across all turns of a session. Methods are pure functions
        of ``(self, *args)``; implementations should not rely on
        mutable per-thread state.
    """

    def get_base_dir(self) -> Path:
        """Return the base directory for all runtime data.

        Returns:
            Absolute path to the root directory under which all other
            runtime data (threads, users, agents, skills) is stored.
        """
        ...

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the per-thread workspace directory.

        The workspace is the primary working area for the agent within
        a given thread. The agent reads and writes files here during
        execution.

        Args:
            thread_id: Identifier of the current conversation thread.
                Implementations may validate this (e.g. restrict to a
                safe character set) and raise ``ValueError`` for
                invalid IDs.
            user_id: Identifier of the owning user. When ``None``
                (default), the implementation may use a fallback
                bucket (e.g. ``"default"``) for backward
                compatibility with unauthenticated contexts.

        Returns:
            Absolute path to the thread's workspace directory.
        """
        ...

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the per-thread uploads directory.

        User-uploaded files (e.g. attachments) are staged here at the
        start of a thread and remain available for the lifetime of the
        thread.

        Args:
            thread_id: Identifier of the current conversation thread.
            user_id: Identifier of the owning user. When ``None``,
                falls back to a default bucket.

        Returns:
            Absolute path to the thread's uploads directory.
        """
        ...

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the per-thread outputs directory.

        Agent-generated artifacts that should be visible to the user
        (e.g. reports, rendered files) are placed here. The
        ``present_files`` tool restricts user-facing output to this
        directory by default.

        Args:
            thread_id: Identifier of the current conversation thread.
            user_id: Identifier of the owning user. When ``None``,
                falls back to a default bucket.

        Returns:
            Absolute path to the thread's outputs directory.
        """
        ...

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the per-thread user-data root directory.

        The user-data root is the common parent of workspace, uploads,
        and outputs. It is the "what the agent sees" boundary — sandbox
        containers typically mount this directory under a virtual path
        (e.g. ``/mnt/user-data`` for DeerFlow).

        Args:
            thread_id: Identifier of the current conversation thread.
            user_id: Identifier of the owning user. When ``None``,
                falls back to a default bucket.

        Returns:
            Absolute path to the thread's user-data root directory.
        """
        ...

    def get_skills_dir(self) -> Path:
        """Return the skills directory (global, not per-thread).

        Skills (SKILL.md files) are loaded from a single global
        directory shared across all threads. Implementations may
        return a path that does not yet exist on disk; the SDK
        creates it on first use.

        Returns:
            Absolute path to the skills directory.
        """
        ...

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the default Python virtual environment directory.

        Used by sandboxed command execution to prefer a thread-local
        venv (``<workspace>/.venv``) over a system Python. Returns
        ``None`` if the runtime does not want to provide a default venv
        hint.

        Args:
            thread_id: Identifier of the current conversation thread.
            user_id: Identifier of the owning user. When ``None``,
                falls back to a default bucket.

        Returns:
            Absolute path to the default venv directory, or ``None``
            if no default is configured.
        """
        ...

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        """Recursively delete the per-thread data directory.

        Removes the entire ``users/{uid}/threads/{tid}/`` subtree
        (workspace, uploads, outputs, and any sibling
        directories used by the implementation). Used by conversation
        cleanup to free disk space when a conversation is deleted.

        Implementations MUST be idempotent — missing directories are
        silently ignored. Bind-mount volumes held open by sandbox
        containers may cause deletion to fail on Linux; callers
        should release / destroy the sandbox first when possible.

        Args:
            thread_id: Identifier of the conversation thread to clean
                up. Implementations should validate the same way as
                their path-producing methods.
            user_id: Identifier of the owning user. When ``None``
                (default), the implementation may use a fallback
                bucket (e.g. ``"default"``) for backward compatibility
                with unauthenticated contexts.
        """
        ...

    def get_virtual_prefix(self) -> str:
        """Return the virtual path prefix seen by sandboxed agents.

        The virtual prefix is what the agent sees inside its sandbox
        (e.g. ``/mnt/user-data`` for DeerFlow). Used by
        :class:`VirtualPathResolver` to translate between physical
        and virtual paths.

        Returns:
            Virtual path prefix string (must start with ``/``).
        """
        ...

    def is_host_bash_allowed(self) -> bool:
        """Whether host-side bash execution is permitted.

        Some deployments (e.g. DeerFlow's local sandbox) disallow
        running bash on the host for safety. The runtime consults this
        to decide whether to allow ``bash`` / local execution tools.

        Returns:
            ``True`` if host bash is allowed, ``False`` otherwise.
        """
        ...
