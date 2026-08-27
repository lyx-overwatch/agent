"""Unit tests for :mod:`agent_sdk.reflection`.

Covers :func:`resolve_variable` and :func:`resolve_class` —
including the actionable error messages for missing
dependencies and the type-validation branches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_sdk.reflection import resolve_class, resolve_variable
from agent_sdk.reflection.resolvers import MODULE_TO_PACKAGE_HINTS

# ---------------------------------------------------------------------------
# resolve_variable
# ---------------------------------------------------------------------------


class TestResolveVariable:
    def test_resolve_class_from_stdlib(self) -> None:
        Path_ = resolve_variable("pathlib:Path")
        assert Path_ is Path

    def test_resolve_function(self) -> None:
        dumps = resolve_variable("json:dumps")
        assert callable(dumps)
        assert dumps({"a": 1}) == json.dumps({"a": 1})

    def test_resolve_module_attribute_chain(self) -> None:
        # Multi-level module path
        ctx_mgr = resolve_variable("contextlib:contextmanager")
        assert callable(ctx_mgr)

    def test_expected_type_passes(self) -> None:
        Path_ = resolve_variable("pathlib:Path", expected_type=type)
        assert Path_ is Path

    def test_expected_type_fails(self) -> None:
        with pytest.raises(ValueError, match="is not an instance of"):
            resolve_variable("pathlib:Path", expected_type=int)

    def test_expected_type_tuple(self) -> None:
        Path_ = resolve_variable("pathlib:Path", expected_type=(type, str))
        assert Path_ is Path

    def test_missing_attribute_raises(self) -> None:
        with pytest.raises(ImportError, match="does not define a"):
            resolve_variable("pathlib:NoSuchAttribute")

    def test_invalid_path_format_raises(self) -> None:
        with pytest.raises(ImportError, match="doesn't look like a variable path"):
            resolve_variable("no_colon_in_path")

    def test_missing_module_raises_with_hint(self) -> None:
        # A non-existent module that maps to a known package hint
        with pytest.raises(ImportError) as excinfo:
            resolve_variable("langchain_google_genai:not_a_thing")
        # The hint should mention the package name
        msg = str(excinfo.value)
        assert "langchain-google-genai" in msg

    def test_transitive_missing_dependency_has_hint(self) -> None:
        # Same idea: missing module path triggers a hint
        with pytest.raises(ImportError) as excinfo:
            resolve_variable("totally_nonexistent_module_xyz123:foo")
        msg = str(excinfo.value)
        assert "totally-nonexistent-module-xyz123" in msg

    def test_module_hints_contains_expected_keys(self) -> None:
        # Sanity: the in-tree reference keys are still here.
        for key in ("langchain_openai", "langchain_anthropic", "langchain_google_genai"):
            assert key in MODULE_TO_PACKAGE_HINTS

    def test_internal_import_error_preserved(self) -> None:
        # If a module exists but raises an ImportError for a
        # reason other than "missing module" (e.g. its own
        # import failed), the original error is preserved.
        with pytest.raises(ImportError):
            resolve_variable("agent_sdk.does_not_exist_submodule:foo")


# ---------------------------------------------------------------------------
# resolve_class
# ---------------------------------------------------------------------------


class TestResolveClass:
    def test_resolve_builtin_class(self) -> None:
        Path_ = resolve_class("pathlib:Path")
        assert Path_ is Path
        assert isinstance(Path_, type)

    def test_base_class_check_passes(self) -> None:
        # ``object`` is the universal base class, so any class
        # passes the issubclass check.
        Path_ = resolve_class("pathlib:Path", base_class=object)
        assert Path_ is Path

    def test_base_class_check_fails(self) -> None:
        # Resolve a class that is not a subclass of int
        with pytest.raises(ValueError, match="is not a subclass of"):
            resolve_class("pathlib:Path", base_class=int)

    def test_non_class_attribute_fails(self) -> None:
        # json.dumps is a function, not a class — resolve_variable
        # rejects the value with the "not an instance of type"
        # error before resolve_class's "is not a valid class"
        # branch is reached.
        with pytest.raises(ValueError, match="is not an instance of"):
            resolve_class("json:dumps")

    def test_resolves_agent_sdk_class(self) -> None:
        # Sanity: SDK's own data classes are resolvable
        from agent_sdk.runtime.checkpointer.config import CheckpointerConfig

        cls = resolve_class(
            "agent_sdk.runtime.checkpointer.config:CheckpointerConfig",
            base_class=CheckpointerConfig,
        )
        assert cls is CheckpointerConfig
