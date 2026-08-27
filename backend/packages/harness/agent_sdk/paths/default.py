"""Default PathProvider with no business assumptions.

:class:`DefaultPathProvider` is a brand-neutral implementation that makes
no assumption about virtual path prefixes, mount layouts, or product
naming. The base directory defaults to ``./.agent-sdk`` (a sibling of
the project's working directory) and can be overridden.

This is the implementation to use when adopting the SDK outside of
DeerFlow — e.g. for a fresh project, an embedded agent, or a test
sandbox.

The default implementation intentionally:
    * does **not** use ``/mnt/user-data`` (which is DeerFlow-specific)
    * does **not** use ``.deer-flow`` (which is the DeerFlow product
      state directory)
    * does **not** validate thread IDs as strictly as DeerFlow does
      (callers may layer their own validation on top)
"""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class DefaultPathProvider:
    """Base-relative path provider with no product assumptions.

    Args:
        base_dir: Root directory under which all runtime data is
            stored. Defaults to ``./.agent-sdk`` relative to the
            current working directory.
    """

    VIRTUAL_PREFIX = "/agent-data"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            self._base_dir = Path("./.agent-sdk").resolve()
        else:
            self._base_dir = Path(base_dir).resolve()

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _uid(user_id: str | None) -> str:
        """Resolve *user_id* to a filesystem-safe bucket name.

        Returns *user_id* unmodified when it is a non-empty string;
        falls back to ``"default"`` for ``None`` or empty.
        """
        return user_id or "default"

    @staticmethod
    def _validate_thread_id(thread_id: str) -> str:
        """Validate a thread ID before using it in filesystem paths.

        Default validation mirrors the conservative pattern in the
        original DeerFlow Paths class: alphanumeric, underscore, and
        hyphen only. This is overridable by callers via a different
        :class:`PathProvider` implementation.
        """
        if not _SAFE_THREAD_ID_RE.match(thread_id):
            raise ValueError(
                f"Invalid thread_id {thread_id!r}: only alphanumeric characters, "
                "hyphens, and underscores are allowed."
            )
        return thread_id

    # ── Base / skills ────────────────────────────────────────────────

    def get_base_dir(self) -> Path:
        return self._base_dir

    def get_skills_dir(self) -> Path:
        return self._base_dir / "skills"

    def get_virtual_prefix(self) -> str:
        return self.VIRTUAL_PREFIX

    def is_host_bash_allowed(self) -> bool:
        """Default provider permits host bash.

        Brand-neutral default: the SDK does not impose a security
        posture. Implementations that want stricter rules (e.g. the
        DeerFlow preset) should override this and return ``False``.
        """
        return True

    # ── Per-thread paths ─────────────────────────────────────────────

    def get_thread_dir(self, thread_id: str) -> Path:
        """Return the per-thread root directory (backward-compat, uses default user bucket).

        New code should prefer the per-thread methods that accept ``user_id``.
        """
        return self._base_dir / "threads" / self._validate_thread_id(thread_id)

    def _thread_dir(self, thread_id: str, user_id: str | None) -> Path:
        """Return the per-user per-thread root directory.

        Layout: ``{base}/users/{uid}/threads/{tid}``
        """
        return self._base_dir / "users" / self._uid(user_id) / "threads" / self._validate_thread_id(thread_id)

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "workspace"

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "uploads"

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self._thread_dir(thread_id, user_id) / "outputs"

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """Return the per-thread user-data root.

        For the default provider, the user-data root is the thread
        directory itself (workspace/uploads/outputs are siblings).
        This differs from DeerFlow where they are nested under
        ``user-data/``.
        """
        return self._thread_dir(thread_id, user_id)

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_workspace_dir(thread_id, user_id=user_id) / ".venv"

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        """Recursively delete the per-thread data directory.

        Idempotent — missing directories are ignored. The whole
        ``users/{uid}/threads/{tid}/`` subtree is removed, including
        workspace / uploads / outputs and any other
        per-thread siblings. Validation matches the path-producing
        methods (alphanumeric / underscore / hyphen only).
        """
        import shutil

        thread_dir = self._thread_dir(thread_id, user_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)
