"""Golden fixture / regression tests for sandbox tool consistency.

These tests verify that the SDK sandbox tools produce consistent
output for known inputs.  They serve as regression tests that can
be extended with backend golden fixtures when available.

For full tool behavior tests, see ``tests/sandbox/test_tools.py``
(318 test cases covering all 7 sandbox tools).
"""

from __future__ import annotations

from agent_sdk.sandbox.path_resolver import SandboxPathResolver, SandboxToolsConfig
from agent_sdk.sandbox.tools import SandboxToolsBundle, make_sandbox_tools


class _FakeProvider:
    def acquire(self, thread_id: str) -> str:
        return "sid-1"

    def get(self, sandbox_id: str):
        return None

    def release(self, sandbox_id: str) -> None:
        pass


class TestSandboxToolConstruction:
    """Verify sandbox tools are constructed correctly."""

    def test_all_seven_tools_created(self) -> None:
        config = SandboxToolsConfig()
        bundle = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        assert isinstance(bundle, SandboxToolsBundle)
        assert bundle.bash is not None
        assert bundle.ls is not None
        assert bundle.glob is not None
        assert bundle.grep is not None
        assert bundle.read_file is not None
        assert bundle.write_file is not None
        assert bundle.str_replace is not None

    def test_tool_names_are_brand_neutral(self) -> None:
        config = SandboxToolsConfig()
        bundle = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        assert bundle.bash.name == "bash"
        assert bundle.ls.name == "ls"
        assert bundle.glob.name == "glob"
        assert bundle.grep.name == "grep"
        assert bundle.read_file.name == "read_file"
        assert bundle.write_file.name == "write_file"
        assert bundle.str_replace.name == "str_replace"

    def test_tool_name_prefix(self) -> None:
        config = SandboxToolsConfig()
        bundle = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
            name_prefix="sandbox_",
        )
        assert bundle.bash.name == "sandbox_bash"
        assert bundle.read_file.name == "sandbox_read_file"

    def test_tools_have_descriptions(self) -> None:
        config = SandboxToolsConfig()
        bundle = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        for tool in [
            bundle.bash,
            bundle.ls,
            bundle.glob,
            bundle.grep,
            bundle.read_file,
            bundle.write_file,
            bundle.str_replace,
        ]:
            assert tool.description, f"{tool.name} should have a description"
            assert len(tool.description) > 20, (
                f"{tool.name} description is too short: {tool.description!r}"
            )

    def test_tools_have_args_schema(self) -> None:
        config = SandboxToolsConfig()
        bundle = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        for tool in [
            bundle.bash,
            bundle.ls,
            bundle.glob,
            bundle.grep,
            bundle.read_file,
            bundle.write_file,
            bundle.str_replace,
        ]:
            assert tool.args_schema is not None, (
                f"{tool.name} should have an args_schema"
            )

    def test_reproducible_construction(self) -> None:
        """Verify that constructing tools twice produces equivalent results."""
        config = SandboxToolsConfig()
        bundle1 = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        bundle2 = make_sandbox_tools(
            sandbox_provider=_FakeProvider(),
            resolver=SandboxPathResolver(config),
        )
        assert bundle1.bash.name == bundle2.bash.name
        assert bundle1.bash.description == bundle2.bash.description