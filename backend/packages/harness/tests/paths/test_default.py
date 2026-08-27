"""Unit tests for :class:`agent_sdk.paths.default.DefaultPathProvider`.

These tests verify the brand-neutral default path provider that ships
with the SDK. The default provider makes no business assumptions; it
must work for any project that adopts the SDK outside of DeerFlow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_sdk.paths import DefaultPathProvider


class TestDefaultPathProviderBaseDir:
    def test_default_base_dir_is_under_dot_agent_sdk(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Run from a clean cwd so the default ``./.agent-sdk`` resolves
        # to ``tmp_path/.agent-sdk``.
        monkeypatch.chdir(tmp_path)
        provider = DefaultPathProvider()
        assert provider.get_base_dir() == (tmp_path / ".agent-sdk").resolve()

    def test_explicit_base_dir_is_respected(self, tmp_path: Path) -> None:
        provider = DefaultPathProvider(base_dir=tmp_path / "custom-base")
        assert provider.get_base_dir() == (tmp_path / "custom-base").resolve()

    def test_string_base_dir_is_coerced(self, tmp_path: Path) -> None:
        provider = DefaultPathProvider(base_dir=str(tmp_path / "from-string"))
        assert provider.get_base_dir() == (tmp_path / "from-string").resolve()


class TestDefaultPathProviderPerThread:
    @pytest.fixture
    def provider(self, tmp_path: Path) -> DefaultPathProvider:
        return DefaultPathProvider(base_dir=tmp_path / ".agent-sdk")

    def test_thread_dir_uses_safe_id(self, provider: DefaultPathProvider) -> None:
        # get_thread_dir uses the legacy flat layout (backward compat).
        assert provider.get_thread_dir("abc-123") == provider.get_base_dir() / "threads" / "abc-123"

    def test_workspace_dir(self, provider: DefaultPathProvider) -> None:
        assert provider.get_workspace_dir("t1") == provider.get_base_dir() / "users" / "default" / "threads" / "t1" / "workspace"

    def test_uploads_dir(self, provider: DefaultPathProvider) -> None:
        assert provider.get_uploads_dir("t1") == provider.get_base_dir() / "users" / "default" / "threads" / "t1" / "uploads"

    def test_outputs_dir(self, provider: DefaultPathProvider) -> None:
        assert provider.get_outputs_dir("t1") == provider.get_base_dir() / "users" / "default" / "threads" / "t1" / "outputs"

    def test_user_data_dir_is_the_user_thread_dir(self, provider: DefaultPathProvider) -> None:
        # For the default provider, the user-data root equals the
        # per-user thread directory (workspace/uploads/outputs are
        # siblings under users/{uid}/threads/{tid}/).
        assert provider.get_user_data_dir("t1") == provider.get_base_dir() / "users" / "default" / "threads" / "t1"

    def test_default_venv_dir(self, provider: DefaultPathProvider) -> None:
        assert provider.get_default_venv_dir("t1") == provider.get_workspace_dir("t1") / ".venv"

    def test_skills_dir_is_global(self, provider: DefaultPathProvider) -> None:
        assert provider.get_skills_dir() == provider.get_base_dir() / "skills"


class TestDefaultPathProviderVirtualPrefix:
    def test_virtual_prefix_is_brand_neutral(self, tmp_path: Path) -> None:
        # The default provider must NOT use /mnt/user-data (DeerFlow-specific).
        provider = DefaultPathProvider(base_dir=tmp_path)
        assert provider.get_virtual_prefix() != "/mnt/user-data"
        assert provider.get_virtual_prefix().startswith("/")

    def test_host_bash_is_allowed_by_default(self, tmp_path: Path) -> None:
        # The default provider does not impose a security posture; the
        # caller can layer their own on top. DeerFlow overrides this
        # to False in the preset.
        provider = DefaultPathProvider(base_dir=tmp_path)
        assert provider.is_host_bash_allowed() is True


class TestDefaultPathProviderValidation:
    @pytest.fixture
    def provider(self, tmp_path: Path) -> DefaultPathProvider:
        return DefaultPathProvider(base_dir=tmp_path)

    @pytest.mark.parametrize("bad_id", ["", "../etc", "thread/with/slashes", "thread with space", "thread.dot"])
    def test_invalid_thread_ids_are_rejected(self, provider: DefaultPathProvider, bad_id: str) -> None:
        with pytest.raises(ValueError):
            provider.get_workspace_dir(bad_id)

    def test_safe_thread_ids_are_accepted(self, provider: DefaultPathProvider) -> None:
        for safe in ("abc", "thread_1", "thread-2", "ABC-123_xyz"):
            assert provider.get_workspace_dir(safe).name == "workspace"
