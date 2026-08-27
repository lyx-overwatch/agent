"""Bidirectional virtual ↔ physical path translation.

The agent inside a sandbox sees paths under a virtual prefix
(``/mnt/user-data`` for DeerFlow, ``/agent-data`` for the default
provider, or any prefix the user chooses). On the host, those paths
correspond to real directories under a thread's ``workspace``,
``uploads``, or ``outputs`` directory.

:class:`VirtualPathResolver` translates between the two views. It is
the single component that knows the virtual-to-physical mapping; the
rest of the runtime only deals with physical paths.

Security:
    :meth:`resolve` and :meth:`virtualize` both anchor on the
    provider's per-thread directories. :meth:`resolve` rejects paths
    that try to escape the user-data root (path-traversal guard) —
    mirroring the original ``backend.config.paths.Paths.resolve_virtual_path``
    behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent_sdk.runtime.user_context import get_effective_user_id

if TYPE_CHECKING:
    from agent_sdk.paths.provider import PathProvider


class VirtualPathResolver:
    """Translates between virtual sandbox paths and physical host paths.

    Args:
        path_provider: A :class:`PathProvider` whose per-thread
            directories anchor the virtual ↔ physical mapping.
    """

    #: Subdirectories under the user-data root that are reachable
    #: from inside the sandbox. Anything else under the user-data
    #: root is not exposed by default.
    EXPOSED_SUBDIRS: tuple[str, ...] = ("workspace", "uploads", "outputs")

    def __init__(self, path_provider: PathProvider) -> None:
        self._provider = path_provider

    @property
    def virtual_prefix(self) -> str:
        """The virtual prefix as configured on the underlying provider."""
        return self._provider.get_virtual_prefix()

    def _candidate_physical_roots(self, thread_id: str) -> list[tuple[str, Path]]:
        """Return ``(subdir, physical_dir)`` pairs in priority order.

        Used by both :meth:`virtualize` and :meth:`resolve` to find
        the right anchor. The list mirrors the exposed subdirs.
        """
        user_id = get_effective_user_id()
        return [
            ("workspace", self._provider.get_workspace_dir(thread_id, user_id=user_id)),
            ("uploads", self._provider.get_uploads_dir(thread_id, user_id=user_id)),
            ("outputs", self._provider.get_outputs_dir(thread_id, user_id=user_id)),
        ]

    def virtualize(self, physical: Path, thread_id: str) -> str:
        """Convert a physical path to a virtual path string.

        If ``physical`` lies under one of the exposed subdirectories
        (workspace / uploads / outputs), the matching virtual path is
        returned. Otherwise the physical path is returned as a string
        unchanged — useful for masking only the parts of an output
        that look like user-data paths.

        Args:
            physical: A physical path (host-side).
            thread_id: The current conversation thread.

        Returns:
            A virtual path string, e.g. ``/mnt/user-data/outputs/report.pdf``.
        """
        physical_resolved = physical.resolve()
        prefix = self.virtual_prefix
        for subdir, root in self._candidate_physical_roots(thread_id):
            try:
                rel = physical_resolved.relative_to(root.resolve())
            except ValueError:
                continue
            return f"{prefix}/{subdir}/{rel.as_posix()}"
        return str(physical)

    def resolve(self, virtual: str, thread_id: str) -> Path:
        """Convert a virtual sandbox path to a physical host path.

        Mirrors the original ``backend.config.paths.Paths.resolve_virtual_path``
        semantics:

        * If the path does not start with the virtual prefix, it is
          returned as ``Path(virtual)`` unchanged.
        * If the path tries to escape the user-data root via
          ``..`` segments, raises ``ValueError``.

        Args:
            virtual: A virtual path, e.g. ``/mnt/user-data/outputs/report.pdf``.
            thread_id: The current conversation thread.

        Returns:
            The resolved absolute physical path.

        Raises:
            ValueError: If the virtual path does not start with the
                expected prefix, or if path traversal is detected.
        """
        prefix = self.virtual_prefix
        prefix_stripped = prefix.lstrip("/")

        # Match the prefix exactly or as a segment prefix to avoid
        # false matches (e.g. ``/mnt/user-dataX/...`` should not
        # count as a match for ``/mnt/user-data``).
        stripped = virtual.lstrip("/")
        if stripped != prefix_stripped and not stripped.startswith(prefix_stripped + "/"):
            # Outside the virtual prefix: pass through as-is.
            return Path(virtual)

        # Anchor on the user-data root, then resolve and verify the
        # result stays inside it.
        user_id = get_effective_user_id()
        user_data_dir = self._provider.get_user_data_dir(thread_id, user_id=user_id).resolve()
        relative = stripped[len(prefix_stripped):].lstrip("/")
        actual = (user_data_dir / relative).resolve()

        try:
            actual.relative_to(user_data_dir)
        except ValueError as exc:
            raise ValueError("Access denied: path traversal detected") from exc

        return actual
