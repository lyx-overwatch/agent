"""Unit tests for :class:`agent_sdk.presets.deerflow.DeerFlowPathProvider`.

These tests verify that the DeerFlow preset provider is byte-for-byte
compatible with the original ``backend.config.paths.Paths`` class —
without importing the original. The expected paths are encoded as
inline fixtures (rather than imported from ``backend.*``) per
ADR-010.

Compatibility scope:
    * Path layout (``{base}/threads/{tid}/user-data/{workspace,uploads,outputs}``)
    * Thread ID validation rule
    * Virtual prefix is ``/mnt/user-data``
    * Host bash is disallowed
    * Base dir resolution order (constructor > DEER_FLOW_HOME > fallback)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_sdk.presets.deerflow import DeerFlowPathProvider


class TestDeerFlowPathProviderBaseDir:
    def test_explicit_base_dir_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Even with DEER_FLOW_HOME set, the constructor argument must win.
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "from-env"))
        provider = DeerFlowPathProvider(base_dir=tmp_path / "from-arg")
        assert provider.get_base_dir() == (tmp_path / "from-arg").resolve()

    def test_env_var_used_when_no_constructor_arg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "from-env"))
        provider = DeerFlowPathProvider()
        assert provider.get_base_dir() == (tmp_path / "from-env").resolve()

    def test_fallback_used_when_neither_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEER_FLOW_HOME", raising=False)
        provider = DeerFlowPathProvider()
        # The fallback walks up 4 parents from this file to backend/ then
        # appends ``.deer-flow``. We only assert that the path is
        # absolute and ends with ``.deer-flow``; the exact location
        # depends on the test process's working tree, but the suffix is
        # a stable contract.
        base = provider.get_base_dir()
        assert base.is_absolute()
        assert base.name == ".deer-flow"


class TestDeerFlowPathProviderLayout:
    """Byte-for-byte compatibility with ``backend.config.paths.Paths``
    — extended with multi-user ``users/{uid}/`` layer."""

    @pytest.fixture
    def provider(self, tmp_path: Path) -> DeerFlowPathProvider:
        return DeerFlowPathProvider(base_dir=tmp_path / "data")

    def test_thread_dir_legacy_flat(self, provider: DeerFlowPathProvider) -> None:
        # get_thread_dir preserves the old flat layout for backward compat.
        assert provider.get_thread_dir("abc") == (provider.get_base_dir() / "threads" / "abc")

    def test_user_data_dir_uses_user_layer(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_user_data_dir("abc") == provider.get_base_dir() / "users" / "default" / "threads" / "abc" / "user-data"

    def test_workspace_dir(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_workspace_dir("abc") == provider.get_user_data_dir("abc") / "workspace"

    def test_uploads_dir(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_uploads_dir("abc") == provider.get_user_data_dir("abc") / "uploads"

    def test_outputs_dir(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_outputs_dir("abc") == provider.get_user_data_dir("abc") / "outputs"

    def test_default_venv_dir(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_default_venv_dir("abc") == provider.get_workspace_dir("abc") / ".venv"

    def test_skills_dir_is_global(self, provider: DeerFlowPathProvider) -> None:
        assert provider.get_skills_dir() == provider.get_base_dir() / "skills"


class TestDeerFlowPathProviderVirtualPrefix:
    def test_virtual_prefix_is_mnt_user_data(self, tmp_path: Path) -> None:
        provider = DeerFlowPathProvider(base_dir=tmp_path)
        assert provider.get_virtual_prefix() == "/mnt/user-data"

    def test_host_bash_is_disallowed(self, tmp_path: Path) -> None:
        # The local sandbox's policy is: never run bash on the host.
        # Mirrors backend.sandbox.security.is_host_bash_allowed().
        provider = DeerFlowPathProvider(base_dir=tmp_path)
        assert provider.is_host_bash_allowed() is False


class TestDeerFlowPathProviderValidation:
    @pytest.fixture
    def provider(self, tmp_path: Path) -> DeerFlowPathProvider:
        return DeerFlowPathProvider(base_dir=tmp_path)

    @pytest.mark.parametrize("bad_id", ["", "../etc", "thread/with/slashes", "thread with space", "thread.dot"])
    def test_invalid_thread_ids_are_rejected(self, provider: DeerFlowPathProvider, bad_id: str) -> None:
        with pytest.raises(ValueError):
            provider.get_workspace_dir(bad_id)

    def test_safe_thread_ids_are_accepted(self, provider: DeerFlowPathProvider) -> None:
        for safe in ("abc", "thread_1", "thread-2", "ABC-123_xyz"):
            assert provider.get_workspace_dir(safe).name == "workspace"


class TestDeerFlowPathProviderGoldenLayout:
    """Snapshot test: the layout for a known base_dir is recorded as a
    string, to catch any accidental refactor that shifts the path
    layout. The expected string is hand-written (not imported) per
    ADR-010.
    """

    def test_layout_snapshot(self, tmp_path: Path) -> None:
        provider = DeerFlowPathProvider(base_dir=tmp_path / "data")
        tid = "thread-42"
        lines = [
            str(provider.get_base_dir()),
            str(provider.get_thread_dir(tid)),
            str(provider.get_user_data_dir(tid)),
            str(provider.get_workspace_dir(tid)),
            str(provider.get_uploads_dir(tid)),
            str(provider.get_outputs_dir(tid)),
            str(provider.get_default_venv_dir(tid)),
            str(provider.get_skills_dir()),
        ]
        actual = "\n".join(lines)
        expected = "\n".join(
            [
                str((tmp_path / "data").resolve()),
                str((tmp_path / "data" / "threads" / "thread-42").resolve()),  # legacy get_thread_dir
                str((tmp_path / "data" / "users" / "default" / "threads" / "thread-42" / "user-data").resolve()),
                str((tmp_path / "data" / "users" / "default" / "threads" / "thread-42" / "user-data" / "workspace").resolve()),
                str((tmp_path / "data" / "users" / "default" / "threads" / "thread-42" / "user-data" / "uploads").resolve()),
                str((tmp_path / "data" / "users" / "default" / "threads" / "thread-42" / "user-data" / "outputs").resolve()),
                str((tmp_path / "data" / "users" / "default" / "threads" / "thread-42" / "user-data" / "workspace" / ".venv").resolve()),
                str((tmp_path / "data" / "skills").resolve()),
            ]
        )
        assert actual == expected
