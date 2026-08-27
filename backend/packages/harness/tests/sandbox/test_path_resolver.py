"""Unit tests for :mod:`agent_sdk.sandbox.path_resolver`."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_sdk.sandbox.exceptions import SandboxRuntimeError
from agent_sdk.sandbox.path_resolver import (
    CustomMount,
    SandboxPathResolver,
    SandboxToolsConfig,
    get_path_resolver,
    reset_path_resolver,
    set_path_resolver,
)

# ---------------------------------------------------------------------------
# SandboxToolsConfig
# ---------------------------------------------------------------------------


class TestConfig:
    def test_defaults(self) -> None:
        c = SandboxToolsConfig()
        assert c.virtual_path_prefix == "/mnt/user-data"
        assert c.custom_mounts == []
        assert c.bash_output_max_chars == 20000
        assert c.ls_output_max_chars == 20000
        assert c.read_file_output_max_chars == 50000

    def test_mcp_paths_provider_default_empty(self) -> None:
        c = SandboxToolsConfig()
        assert c.mcp_allowed_paths_provider() == []

    def test_custom_mount_dataclass(self) -> None:
        m = CustomMount(host_path="/data", container_path="/mnt/data", read_only=True)
        assert m.host_path == "/data"
        assert m.container_path == "/mnt/data"
        assert m.read_only is True


# ---------------------------------------------------------------------------
# Path family predicates
# ---------------------------------------------------------------------------


def _resolver(**overrides) -> SandboxPathResolver:
    return SandboxPathResolver(SandboxToolsConfig(**overrides))


def _td() -> dict:
    """Standard thread_data for resolver tests."""
    return {
        "workspace_path": "/var/ws",
        "uploads_path": "/var/up",
        "outputs_path": "/var/out",
    }


class TestPathPredicates:
    def test_user_data_predicate(self) -> None:
        r = _resolver()
        assert r.is_user_data_path("/mnt/user-data") is True
        assert r.is_user_data_path("/mnt/user-data/workspace/x.py") is True
        assert r.is_user_data_path("/other") is False

    def test_custom_mount_predicate(self) -> None:
        r = _resolver(custom_mounts=[CustomMount("/h", "/mnt/data"), CustomMount("/h2", "/mnt/data2", read_only=True)])
        assert r.is_custom_mount_path("/mnt/data") is True
        assert r.is_custom_mount_path("/mnt/data/x") is True
        assert r.is_custom_mount_path("/mnt/data2") is True
        assert r.is_custom_mount_path("/other") is False

    def test_is_path_family_known(self) -> None:
        r = _resolver(custom_mounts=[CustomMount("/h", "/mnt/data")])
        assert r.is_path_family_known("/mnt/user-data/x") is True
        assert r.is_path_family_known("/mnt/data/x") is True
        assert r.is_path_family_known("/other") is False


# ---------------------------------------------------------------------------
# Module-level resolver binding
# ---------------------------------------------------------------------------


class TestModuleResolver:
    def test_default_resolver_is_brand_neutral(self) -> None:
        # Saving the previous token would normally be needed; we just smoke-test.
        r = get_path_resolver()
        assert isinstance(r, SandboxPathResolver)
        assert r.virtual_path_prefix == "/mnt/user-data"

    def test_set_and_reset(self) -> None:
        custom = SandboxPathResolver(SandboxToolsConfig(virtual_path_prefix="/custom"))
        token = set_path_resolver(custom)
        try:
            assert get_path_resolver() is custom
            assert get_path_resolver().virtual_path_prefix == "/custom"
        finally:
            reset_path_resolver(token)
        # After reset, the resolver is the lazily-built default again.
        assert get_path_resolver() is not custom


# ---------------------------------------------------------------------------
# validate_local_tool_path
# ---------------------------------------------------------------------------


def _thread_data(tmp_path, *, common_parent: bool = True) -> dict:
    """Build a thread_data dict whose three paths share a parent under *tmp_path*."""
    base = tmp_path / "threads" / "t1" / "user-data"
    base.mkdir(parents=True, exist_ok=True)
    if common_parent:
        return {
            "workspace_path": str(base / "workspace"),
            "uploads_path": str(base / "uploads"),
            "outputs_path": str(base / "outputs"),
        }
    return {
        "workspace_path": str(tmp_path / "ws"),
        "uploads_path": str(tmp_path / "up"),
        "outputs_path": str(tmp_path / "out"),
    }


class TestValidateLocalToolPath:
    def test_user_data_allowed(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        r.validate_local_tool_path("/mnt/user-data/workspace/x.py", td)  # no exception

    def test_user_data_read_only_or_writable(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        # Both modes accept user-data.
        r.validate_local_tool_path("/mnt/user-data/x", td, read_only=True)
        r.validate_local_tool_path("/mnt/user-data/x", td, read_only=False)

    def test_custom_mount_read_write(self, tmp_path) -> None:
        m = CustomMount("/data", "/mnt/data", read_only=True)
        r = _resolver(custom_mounts=[m])
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/mnt/data/x", td, read_only=False)
        r.validate_local_tool_path("/mnt/data/x", td, read_only=True)

        # Writable mount accepts both modes.
        m2 = CustomMount("/data2", "/mnt/data2", read_only=False)
        r2 = _resolver(custom_mounts=[m2])
        r2.validate_local_tool_path("/mnt/data2/x", td, read_only=False)
        r2.validate_local_tool_path("/mnt/data2/x", td, read_only=True)

    def test_unknown_path_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/somewhere/else", td)

    def test_traversal_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/mnt/user-data/../etc", td)

    def test_no_thread_data_raises_runtime(self) -> None:
        r = _resolver()
        with pytest.raises(SandboxRuntimeError):
            r.validate_local_tool_path("/mnt/user-data/x", None)


# ---------------------------------------------------------------------------
# resolve_and_validate_user_data_path
# ---------------------------------------------------------------------------


class TestResolveAndValidateUserDataPath:
    def test_workspace_resolves(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        out = r.resolve_and_validate_user_data_path("/mnt/user-data/workspace/x.py", td)
        assert out.startswith(ws)
        assert out.endswith("x.py")

    def test_traversal_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.resolve_and_validate_user_data_path("/mnt/user-data/workspace/../../etc", td)


# ---------------------------------------------------------------------------
# replace_virtual_path
# ---------------------------------------------------------------------------


class TestReplaceVirtualPath:
    def test_no_thread_data_passthrough(self) -> None:
        r = _resolver()
        assert r.replace_virtual_path("/mnt/user-data/x", None) == "/mnt/user-data/x"

    def test_workspace(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        out = r.replace_virtual_path("/mnt/user-data/workspace/x.py", td)
        # Use Path to be separator-agnostic (Windows uses ``\``).
        from pathlib import Path

        assert Path(out) == Path(ws) / "x.py"

    def test_uploads(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        up = td["uploads_path"]
        out = r.replace_virtual_path("/mnt/user-data/uploads/y", td)
        from pathlib import Path

        assert Path(out) == Path(up) / "y"

    def test_outputs(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        out = td["outputs_path"]
        result = r.replace_virtual_path("/mnt/user-data/outputs/z", td)
        from pathlib import Path

        assert Path(result) == Path(out) / "z"

    def test_root_when_common_parent(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path, common_parent=True)
        # All three share ``{base}/threads/t1/user-data`` as parent,
        # so the root itself is mapped to that parent.
        from pathlib import Path

        base = tmp_path / "threads" / "t1" / "user-data"
        out = r.replace_virtual_path("/mnt/user-data", td)
        assert Path(out) == base

    def test_root_no_mapping_when_split_parents(self, tmp_path) -> None:
        r = _resolver()
        # Place each dir under a *distinct* parent so the ``common_parent``
        # check fails and the root is not remapped.
        td = {
            "workspace_path": str(tmp_path / "a" / "ws"),
            "uploads_path": str(tmp_path / "b" / "up"),
            "outputs_path": str(tmp_path / "c" / "out"),
        }
        assert r.replace_virtual_path("/mnt/user-data", td) == "/mnt/user-data"

    def test_trailing_slash_preserved(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)

        out = r.replace_virtual_path("/mnt/user-data/workspace/", td)
        # Either separator is acceptable.
        assert out.endswith(("/", "\\"))


# ---------------------------------------------------------------------------
# mask_local_paths_in_output
# ---------------------------------------------------------------------------


class TestMaskLocalPathsInOutput:
    def test_no_thread_data_passthrough(self) -> None:
        r = _resolver()
        assert r.mask_local_paths_in_output("hello", None) == "hello"

    def test_no_mappings_passthrough(self, tmp_path) -> None:
        r = _resolver()
        td: dict = {}  # empty
        assert r.mask_local_paths_in_output("hello", td) == "hello"

    def test_user_data_path_masked(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        output = f"Error opening {ws}/x.py: not found"
        out = r.mask_local_paths_in_output(output, td)
        assert "/mnt/user-data/workspace/x.py" in out
        assert ws not in out

    def test_resolved_path_also_masked(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        # Simulate Path.resolve() rewriting the prefix.
        resolved = str((tmp_path / "threads" / "t1" / "user-data" / "workspace").resolve())
        output = f"file at {resolved}/x.py"
        out = r.mask_local_paths_in_output(output, td)
        assert "/mnt/user-data/workspace/x.py" in out


# ---------------------------------------------------------------------------
# validate_local_bash_command_paths
# ---------------------------------------------------------------------------


class TestValidateLocalBashCommandPaths:
    def test_user_data_path_allowed(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        r.validate_local_bash_command_paths("ls /mnt/user-data/workspace", td)

    def test_no_thread_data_raises_runtime(self) -> None:
        r = _resolver()
        with pytest.raises(SandboxRuntimeError):
            r.validate_local_bash_command_paths("ls /mnt/user-data/workspace", None)

    def test_system_path_allowed(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        # ``/bin/`` and ``/dev/`` are in the system-path allowlist.
        r.validate_local_bash_command_paths("ls /bin/ls", td)
        r.validate_local_bash_command_paths("cat /dev/null", td)

    def test_arbitrary_absolute_path_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("ls /etc/passwd", td)
        # /etc/passwd doesn't match the system prefixes; wait, /etc is not in _LOCAL_BASH_SYSTEM_PATH_PREFIXES
        # Actually the system prefixes are /bin/, /usr/bin/, /usr/sbin/, /sbin/, /opt/homebrew/bin/, /dev/
        # /etc/ is not in there so /etc/passwd is rejected. Good.

    def test_file_url_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cat file:///etc/passwd", td)

    def test_http_url_not_treated_as_path(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        # http:// is a URL — not an absolute path.
        r.validate_local_bash_command_paths("curl https://example.com/x", td)

    def test_dotdot_in_token_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cat /mnt/user-data/workspace/../etc", td)

    def test_unsafe_cd_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cd /etc", td)

    def test_cd_to_user_data_allowed(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        r.validate_local_bash_command_paths("cd /mnt/user-data/workspace && ls", td)

    def test_cd_substitution_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("echo $(cd /etc)", td)

    def test_cd_dash_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cd -", td)

    def test_cd_dollar_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cd $HOME", td)

    def test_cd_tilde_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cd ~", td)

    def test_command_wrapper_around_cd(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        # ``command cd /etc`` -> still rejected.
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("command cd /etc", td)
        # ``command cd /mnt/user-data/workspace`` -> allowed.
        r.validate_local_bash_command_paths("command cd /mnt/user-data/workspace", td)

    def test_root_path_command_rejected(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        # `cat /` is unsafe per the root_path_args rule.
        with pytest.raises(PermissionError):
            r.validate_local_bash_command_paths("cat /", td)

    def test_mcp_allowed_path(self, tmp_path) -> None:
        r = _resolver(
            mcp_allowed_paths_provider=lambda: ["/data/from-mcp/"]
        )
        td = _thread_data(tmp_path)
        r.validate_local_bash_command_paths("cat /data/from-mcp/x", td)

    def test_custom_mount_path(self, tmp_path) -> None:
        r = _resolver(custom_mounts=[CustomMount("/x", "/mnt/data", read_only=False)])
        td = _thread_data(tmp_path)
        r.validate_local_bash_command_paths("cat /mnt/data/x", td)


# ---------------------------------------------------------------------------
# replace_virtual_paths_in_command
# ---------------------------------------------------------------------------


class TestReplaceVirtualPathsInCommand:
    def test_user_data_replaced(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        out = r.replace_virtual_paths_in_command("ls /mnt/user-data/workspace/x", td)
        assert ws in out
        assert "/mnt/user-data" not in out

    def test_no_match_passthrough(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        out = r.replace_virtual_paths_in_command("ls /etc", td)
        assert out == "ls /etc"


# ---------------------------------------------------------------------------
# apply_cwd_prefix
# ---------------------------------------------------------------------------


class TestApplyCwdPrefix:
    def test_with_workspace(self, tmp_path) -> None:
        r = _resolver()
        td = _thread_data(tmp_path)
        ws = td["workspace_path"]
        out = r.apply_cwd_prefix("ls -la", td)
        # shlex.quote may add single quotes on POSIX, but on Windows backslashes are kept as-is.
        assert out.startswith("cd ")
        assert "&& ls -la" in out
        # The quoted workspace is in there somewhere.
        assert ws in out

    def test_no_workspace_passthrough(self) -> None:
        r = _resolver()
        assert r.apply_cwd_prefix("ls -la", None) == "ls -la"
        assert r.apply_cwd_prefix("ls -la", {}) == "ls -la"


# ---------------------------------------------------------------------------
# 5.7 batch-7 cleanup (H-3 + H-5 + M-1 regression tests)
# ---------------------------------------------------------------------------


class TestStrictSubpathValidation:
    """H-3: validate_local_tool_path must reject bare root paths."""

    def test_user_data_root_is_rejected(self) -> None:
        r = _resolver()
        td = _td()
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/mnt/user-data", td, read_only=True)

    def test_user_data_root_with_writable_flag_is_rejected(self) -> None:
        r = _resolver()
        td = _td()
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/mnt/user-data", td, read_only=False)

    def test_user_data_subpath_is_accepted(self) -> None:
        r = _resolver()
        td = _td()
        # Should not raise.
        r.validate_local_tool_path("/mnt/user-data/workspace/x.py", td, read_only=True)

    def test_custom_mount_root_is_rejected(self, tmp_path) -> None:
        host = str(tmp_path / "data")
        Path(host).mkdir()
        r = _resolver(custom_mounts=[CustomMount(host, "/mnt/data", read_only=False)])
        td = _td()
        with pytest.raises(PermissionError):
            r.validate_local_tool_path("/mnt/data", td, read_only=True)


class TestPermissionErrorMessage:
    """M-1: PermissionError wording matches backend (verbatim)."""

    def test_error_message_includes_configured_mount_paths(self, tmp_path) -> None:
        host = str(tmp_path / "data")
        Path(host).mkdir()
        r = _resolver(custom_mounts=[CustomMount(host, "/mnt/data", read_only=False)])
        td = _td()
        with pytest.raises(PermissionError) as exc_info:
            r.validate_local_tool_path("/etc", td, read_only=True)
        # Backend-aligned phrasing: "Only paths under ... or configured mount paths are allowed"
        msg = str(exc_info.value)
        assert "Only paths under" in msg
        assert "or configured mount paths are allowed" in msg


class TestCustomMountsFiltering:
    """H-5: SandboxToolsConfig.with_existing_mounts_only filters non-existent paths."""

    def test_existing_mounts_kept(self, tmp_path) -> None:
        host = str(tmp_path / "data")
        Path(host).mkdir()
        cfg = SandboxToolsConfig.with_existing_mounts_only(
            mounts=[CustomMount(host, "/mnt/data")]
        )
        assert len(cfg.custom_mounts) == 1
        assert cfg.custom_mounts[0].host_path == host

    def test_nonexistent_mounts_filtered_with_warning(self, tmp_path) -> None:
        existing = str(tmp_path / "data")
        Path(existing).mkdir()
        missing = str(tmp_path / "missing")
        with pytest.warns(UserWarning, match="non-existent host_path"):
            cfg = SandboxToolsConfig.with_existing_mounts_only(
                mounts=[
                    CustomMount(existing, "/mnt/data"),
                    CustomMount(missing, "/mnt/missing"),
                ]
            )
        # Only the existing mount survives.
        assert len(cfg.custom_mounts) == 1
        assert cfg.custom_mounts[0].host_path == existing

    def test_resolver_itself_does_not_filter(self, tmp_path) -> None:
        # SandboxPathResolver does NOT filter — caller is responsible
        # (matching the original design). Use with_existing_mounts_only
        # to opt in.
        host = str(tmp_path / "missing")
        # Don't create the directory.
        cfg = SandboxToolsConfig(custom_mounts=[CustomMount(host, "/mnt/data")])
        assert len(cfg.custom_mounts) == 1  # not filtered

