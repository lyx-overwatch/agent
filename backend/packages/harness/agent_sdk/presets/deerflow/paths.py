"""DeerFlow preset: PathProvider preserving ``/mnt/user-data`` behavior.

:class:`DeerFlowPathProvider` is the brand-specific implementation of
:class:`agent_sdk.paths.PathProvider` for the DeerFlow product. It
preserves the path layout and validation rules of the original
``backend.config.paths.Paths`` class **byte-for-byte** so that the
SDK and the existing DeerFlow application remain drop-in compatible.

Notes (per ADR-010 re-implementation):
    * The class is re-implemented from scratch in the SDK; it does
      **not** import ``backend.config.paths.Paths`` or copy any file
      from ``backend/``.
    * The class does **not** include DeerFlow-specific concerns that
      are not path-resolution: USER.md / agents/ / memory.json file
      locations, the ``DEER_FLOW_HOST_BASE_DIR`` Docker Desktop
      fallback, and the 0o777 ``ensure_thread_dirs`` permission dance
      all live elsewhere. They are mentioned in the docstring as a
      reference for the future DeerFlow preset refactor (stage 4),
      not implemented here.
    * The path resolution behavior is verified by golden fixtures in
      ``sdk-extraction/harness/tests/fixtures/paths/`` rather than
      by importing the original ``Paths`` class.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _default_local_base_dir() -> Path:
    """Return the repo-local DeerFlow state directory.

    Mirrors the original ``_default_local_base_dir`` in
    ``backend.config.paths``: walks up four parents from this file
    to find the ``backend/`` directory and returns
    ``backend/.deer-flow``.
    """
    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow"


def _validate_thread_id(thread_id: str) -> str:
    if not _SAFE_THREAD_ID_RE.match(thread_id):
        raise ValueError(
            f"Invalid thread_id {thread_id!r}: only alphanumeric characters, "
            "hyphens, and underscores are allowed."
        )
    return thread_id


class DeerFlowPathProvider:
    """Path provider for DeerFlow (preserves ``/mnt/user-data`` behavior).

    Directory layout (host side, byte-for-byte compatible with the
    original ``backend.config.paths.Paths``)::

        {base_dir}/
        └── users/
            └── {user_id}/
                └── threads/
                    └── {thread_id}/
                        └── user-data/             <-- mounted as /mnt/user-data/ inside sandbox
                            ├── workspace/         <-- /mnt/user-data/workspace/
                            ├── uploads/           <-- /mnt/user-data/uploads/
                            └── outputs/           <-- /mnt/user-data/outputs/

    BaseDir resolution (in priority order):
        1. Constructor argument ``base_dir``
        2. ``DEER_FLOW_HOME`` environment variable
        3. Repo-local fallback derived from this module path:
           ``{sdk-extraction root}/.deer-flow``
    """

    VIRTUAL_PATH_PREFIX = "/mnt/user-data"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _uid(user_id: str | None) -> str:
        """Resolve *user_id* to a filesystem-safe bucket name."""
        return user_id or "default"

    # ── Base / skills ─────────────────────────────────────────────

    def get_base_dir(self) -> Path:
        if self._base_dir is not None:
            return self._base_dir
        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()
        return _default_local_base_dir()

    def get_skills_dir(self) -> Path:
        return self.get_base_dir() / "skills"

    # ── Per-thread paths ──────────────────────────────────────────

    def get_thread_dir(self, thread_id: str) -> Path:
        """Return the per-thread root (without user bucket).

        Kept for backward compatibility; new code should prefer
        the per-thread methods that accept ``user_id``.
        """
        return self.get_base_dir() / "threads" / _validate_thread_id(thread_id)

    def _thread_dir(self, thread_id: str, user_id: str | None) -> Path:
        """Return the per-user per-thread root directory.

        Layout: ``{base}/users/{uid}/threads/{tid}``
        """
        return self.get_base_dir() / "users" / self._uid(user_id) / "threads" / _validate_thread_id(thread_id)

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """The user-data root (mounted as ``/mnt/user-data/``)."""
        return self._thread_dir(thread_id, user_id) / "user-data"

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "workspace"

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "uploads"

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "outputs"

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_workspace_dir(thread_id, user_id=user_id) / ".venv"

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        """Recursively delete the per-thread data directory.

        Removes the entire ``users/{uid}/threads/{tid}/`` subtree,
        including ``user-data/``. Idempotent
        — missing directories are ignored. Same thread_id validation
        as the path-producing methods.
        """
        import shutil

        thread_dir = self._thread_dir(thread_id, user_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    # ── Virtual path prefix ───────────────────────────────────────

    def get_virtual_prefix(self) -> str:
        return self.VIRTUAL_PATH_PREFIX

    # ── Host policy ───────────────────────────────────────────────

    def is_host_bash_allowed(self) -> bool:
        """DeerFlow's local sandbox disallows host bash by default.

        Mirrors ``is_host_bash_allowed()`` in
        ``backend.sandbox.security`` which always returns ``False``
        for the local backend.
        """
        return False
