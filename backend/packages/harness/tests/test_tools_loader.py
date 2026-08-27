"""Unit tests for :mod:`agent_sdk.tools.loader`.

Covers :func:`load_tools`, :class:`ToolConfig`, and
:class:`LoadResult`.  We install a couple of fake tool
classes in ``sys.modules`` so the class-path resolution
paths can be exercised without depending on the real tool
implementations.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from agent_sdk.tools.loader import LoadResult, ToolConfig, load_tools
from langchain_core.tools import BaseTool
from pydantic import Field

# ---------------------------------------------------------------------------
# Fake tools
# ---------------------------------------------------------------------------


class _FakeBaseTool(BaseTool):
    """Minimal BaseTool subclass used to verify the loader plumbing."""

    name: str = Field(default="fake")
    description: str = Field(default="fake tool")

    def _run(self, *args: Any, **kwargs: Any) -> str:
        return "fake-result"

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return "fake-result"


_FAKE_MODULE = "agent_sdk_tests_fake_tool_module"


@pytest.fixture(scope="module", autouse=True)
def _install_fake_tools() -> None:
    if _FAKE_MODULE not in sys.modules:
        mod = types.ModuleType(_FAKE_MODULE)

        class _A(_FakeBaseTool):
            name: str = "a"
            description: str = "A"

        class _B(_FakeBaseTool):
            name: str = "b"
            description: str = "B"

        class _C(_FakeBaseTool):
            name: str = "c"
            description: str = "C"

        mod.A = _A  # type: ignore[attr-defined]
        mod.B = _B  # type: ignore[attr-defined]
        mod.C = _C  # type: ignore[attr-defined]
        sys.modules[_FAKE_MODULE] = mod


# ---------------------------------------------------------------------------
# ToolConfig
# ---------------------------------------------------------------------------


class TestToolConfig:
    def test_minimal(self) -> None:
        c = ToolConfig(name="x", use="m:X")
        assert c.name == "x"
        assert c.use == "m:X"
        assert c.group is None

    def test_with_group(self) -> None:
        c = ToolConfig(name="x", use="m:X", group="bash")
        assert c.group == "bash"


# ---------------------------------------------------------------------------
# load_tools
# ---------------------------------------------------------------------------


class TestLoadTools:
    def test_loads_single_config(self) -> None:
        result = load_tools([ToolConfig(name="a", use=f"{_FAKE_MODULE}:A")])
        assert len(result.tools) == 1
        assert result.tools[0].name == "a"
        assert result.skipped_duplicates == []
        assert result.mismatched_names == []

    def test_loads_multiple_configs(self) -> None:
        result = load_tools(
            [
                ToolConfig(name="a", use=f"{_FAKE_MODULE}:A"),
                ToolConfig(name="b", use=f"{_FAKE_MODULE}:B"),
            ]
        )
        names = [t.name for t in result.tools]
        assert names == ["a", "b"]

    def test_group_filter(self) -> None:
        result = load_tools(
            [
                ToolConfig(name="a", use=f"{_FAKE_MODULE}:A", group="web"),
                ToolConfig(name="b", use=f"{_FAKE_MODULE}:B", group="bash"),
                ToolConfig(name="c", use=f"{_FAKE_MODULE}:C", group="web"),
            ],
            groups=["web"],
        )
        names = [t.name for t in result.tools]
        assert names == ["a", "c"]

    def test_builtin_tools_appended(self) -> None:
        builtin_a = _FakeBaseTool()  # name == "fake"

        class _NamedBuiltin(_FakeBaseTool):
            name: str = "builtin1"

        result = load_tools(
            [ToolConfig(name="a", use=f"{_FAKE_MODULE}:A")],
            builtin_tools=[_NamedBuiltin()],
        )
        names = [t.name for t in result.tools]
        assert names == ["a", "builtin1"]
        assert builtin_a.name == "fake"  # default name unchanged

    def test_extra_tools_appended_last(self) -> None:
        class _NamedExtra(_FakeBaseTool):
            name: str = "extra1"

        result = load_tools(
            [ToolConfig(name="a", use=f"{_FAKE_MODULE}:A")],
            extra_tools=[_NamedExtra()],
        )
        names = [t.name for t in result.tools]
        assert names == ["a", "extra1"]

    def test_duplicate_config_is_skipped(self) -> None:
        # Two configs that resolve to the same tool name.
        result = load_tools(
            [
                ToolConfig(name="a", use=f"{_FAKE_MODULE}:A"),
                ToolConfig(name="a", use=f"{_FAKE_MODULE}:A"),
            ]
        )
        names = [t.name for t in result.tools]
        assert names == ["a"]
        assert result.skipped_duplicates == ["a"]

    def test_duplicate_against_builtin_is_skipped(self) -> None:
        class _NamedBuiltin(_FakeBaseTool):
            name: str = "a"

        result = load_tools(
            [ToolConfig(name="a", use=f"{_FAKE_MODULE}:A")],
            builtin_tools=[_NamedBuiltin()],
        )
        # First occurrence wins; the builtin (which came later)
        # is skipped.
        names = [t.name for t in result.tools]
        assert names == ["a"]
        assert result.skipped_duplicates == ["a"]

    def test_duplicate_against_extra_is_skipped(self) -> None:
        class _NamedExtra(_FakeBaseTool):
            name: str = "a"

        result = load_tools(
            [ToolConfig(name="a", use=f"{_FAKE_MODULE}:A")],
            extra_tools=[_NamedExtra()],
        )
        names = [t.name for t in result.tools]
        assert names == ["a"]
        assert result.skipped_duplicates == ["a"]

    def test_mismatched_name_recorded(self) -> None:
        # Config says "wrong-name" but the tool's .name is "a".
        result = load_tools([ToolConfig(name="wrong-name", use=f"{_FAKE_MODULE}:A")])
        assert result.tools[0].name == "a"  # tool's own name wins
        assert result.mismatched_names == [("wrong-name", "a")]

    def test_invalid_class_path_raises(self) -> None:
        with pytest.raises(ImportError):
            load_tools([ToolConfig(name="x", use="agent_sdk.no_such_module:NoSuch")])

    def test_empty_inputs(self) -> None:
        result = load_tools()
        assert result.tools == []
        assert result.skipped_duplicates == []
        assert result.mismatched_names == []

    def test_return_type(self) -> None:
        result = load_tools()
        assert isinstance(result, LoadResult)
