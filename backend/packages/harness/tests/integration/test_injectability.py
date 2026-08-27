"""End-to-end test: a non-DeerFlow project can use the SDK with custom paths.

Per ADR-001 and ADR-010 the SDK must work for projects that do NOT
adopt DeerFlow's ``/mnt/user-data`` convention. This test exercises
that claim with a minimal ``DefaultPathProvider`` configuration.
"""

from __future__ import annotations

from pathlib import Path

from agent_sdk.paths import DefaultPathProvider, VirtualPathResolver


def test_default_provider_uses_no_mnt_user_data(tmp_path: Path) -> None:
    """A fresh project that adopts the SDK must not see ``/mnt/user-data`` anywhere."""
    provider = DefaultPathProvider(base_dir=tmp_path / "my-project-data")
    resolver = VirtualPathResolver(provider)

    # No virtual path anywhere should start with /mnt/user-data.
    for subdir in ("workspace", "uploads", "outputs"):
        physical = getattr(provider, f"get_{subdir}_dir")("t1") / "file.txt"
        virtual = resolver.virtualize(physical, "t1")
        assert not virtual.startswith("/mnt/user-data"), f"leaked DeerFlow prefix: {virtual}"
        assert virtual.startswith(provider.get_virtual_prefix())


def test_default_provider_can_create_real_directories(tmp_path: Path) -> None:
    """The paths produced are usable on the real filesystem."""
    provider = DefaultPathProvider(base_dir=tmp_path / "data")
    dirs_to_test = [
        provider.get_workspace_dir("t1"),
        provider.get_uploads_dir("t1"),
        provider.get_outputs_dir("t1"),
        provider.get_skills_dir(),
    ]
    for d in dirs_to_test:
        d.mkdir(parents=True, exist_ok=True)
        assert d.is_dir()


def test_round_trip_works_for_all_exposed_subdirs(tmp_path: Path) -> None:
    """virtualize → resolve must be a no-op (modulo the prefix)."""
    provider = DefaultPathProvider(base_dir=tmp_path)
    resolver = VirtualPathResolver(provider)
    for subdir in ("workspace", "uploads", "outputs"):
        for name in ("a.txt", "sub/b.txt", "deep/nested/c.md"):
            physical = getattr(provider, f"get_{subdir}_dir")("tid") / name
            virtual = resolver.virtualize(physical, "tid")
            again = resolver.resolve(virtual, "tid")
            assert again == physical.resolve()


def test_default_provider_does_not_enforce_security_posture(tmp_path: Path) -> None:
    """The default provider does not impose security rules.

    DeerFlow's preset overrides ``is_host_bash_allowed`` to False,
    but the default provider is brand-neutral and must allow it.
    Callers that want stricter rules layer their own on top.
    """
    provider = DefaultPathProvider(base_dir=tmp_path)
    assert provider.is_host_bash_allowed() is True


def test_custom_virtual_prefix_is_respected(tmp_path: Path) -> None:
    """A project can configure any virtual prefix it likes."""

    class _MyProvider(DefaultPathProvider):
        def get_virtual_prefix(self) -> str:
            return "/my-namespace"

    provider = _MyProvider(base_dir=tmp_path)
    resolver = VirtualPathResolver(provider)
    physical = provider.get_workspace_dir("t1") / "x.txt"
    assert resolver.virtualize(physical, "t1") == "/my-namespace/workspace/x.txt"
    assert resolver.resolve("/my-namespace/workspace/x.txt", "t1") == physical.resolve()
