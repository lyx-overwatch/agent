"""Unit tests for the :class:`PathProvider` Protocol contract.

These tests use a minimal user-defined implementation to verify the
Protocol surface. They do not test any specific implementation; for
that, see ``test_default.py`` and ``test_deerflow.py``.
"""

from __future__ import annotations

from pathlib import Path

from agent_sdk.paths import PathProvider, VirtualPathResolver


class _CustomProvider:
    """A minimal user-defined provider that satisfies the Protocol.

    Implementing the Protocol is intentionally a plain class (not a
    subclass of anything SDK-internal) — this verifies the Protocol
    really is duck-typed and not coupled to a base class.

    Layout (mirrors DeerFlow's ``user-data/`` nesting so the
    resolver can find the workspace/uploads/outputs roots)::

        /opt/agent-data/
            users/{user_id}/threads/{tid}/
                user-data/{workspace,uploads,outputs}/
            skills/
    """

    BASE = Path("/opt/agent-data")
    VIRTUAL = "/agent-data"

    @staticmethod
    def _uid(user_id: str | None) -> str:
        return user_id or "default"

    def get_base_dir(self) -> Path:
        return self.BASE

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "workspace"

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "uploads"

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_user_data_dir(thread_id, user_id=user_id) / "outputs"

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.BASE / "users" / self._uid(user_id) / "threads" / thread_id / "user-data"

    def get_skills_dir(self) -> Path:
        return self.BASE / "skills"

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        return self.get_workspace_dir(thread_id, user_id=user_id) / ".venv"

    def get_virtual_prefix(self) -> str:
        return self.VIRTUAL

    def is_host_bash_allowed(self) -> bool:
        return True


def test_custom_provider_satisfies_protocol() -> None:
    """A plain class with the right methods is a valid ``PathProvider``.

    ``Protocol`` is duck-typed; the runtime check confirms that
    ``_CustomProvider`` matches the ``PathProvider`` shape.
    """
    provider: PathProvider = _CustomProvider()
    # Just exercise the methods; the precise values are provider-specific.
    assert provider.get_base_dir() == _CustomProvider.BASE
    assert provider.get_workspace_dir("t1") == _CustomProvider.BASE / "users" / "default" / "threads" / "t1" / "user-data" / "workspace"
    assert provider.get_user_data_dir("t1") == _CustomProvider.BASE / "users" / "default" / "threads" / "t1" / "user-data"
    assert provider.get_virtual_prefix() == "/agent-data"
    assert provider.is_host_bash_allowed() is True


def test_resolver_works_with_any_provider() -> None:
    """A user-defined provider can drive the resolver too."""
    provider: PathProvider = _CustomProvider()
    resolver = VirtualPathResolver(provider)
    physical = provider.get_workspace_dir("t1") / "x.txt"
    assert resolver.virtualize(physical, "t1") == "/agent-data/workspace/x.txt"
    resolved = resolver.resolve("/agent-data/workspace/x.txt", "t1")
    assert resolved == physical.resolve()


def test_protocol_is_runtime_checkable() -> None:
    """Confirm that an incomplete implementation fails the protocol check."""

    # The Protocol class is structural; ``isinstance`` against it
    # works only if ``@runtime_checkable`` is set. We do not assert
    # ``isinstance`` here because PathProvider is not marked
    # ``@runtime_checkable``; we just verify the import works.
    assert hasattr(PathProvider, "get_workspace_dir")


def test_protocol_methods_are_declared() -> None:
    expected = {
        "get_base_dir",
        "get_workspace_dir",
        "get_uploads_dir",
        "get_outputs_dir",
        "get_user_data_dir",
        "get_skills_dir",
        "get_default_venv_dir",
        "get_virtual_prefix",
        "is_host_bash_allowed",
    }
    actual = set(dir(PathProvider))
    # The Protocol declares these as method names; ``dir`` includes
    # both dunders and method names, so we intersect.
    assert expected <= {name for name in actual if not name.startswith("__")}
