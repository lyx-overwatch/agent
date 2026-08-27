"""Resolve Python classes and variables from ``"module.path:attribute"`` strings.

This module is a re-implementation (per ADR-010) of
``deerflow.reflection.resolvers``.  It provides two generic
helpers used throughout the SDK and the DeerFlow preset to
load classes by config string.

Examples
--------
>>> cls = resolve_class("pathlib:Path")
>>> issubclass(cls, Path)
True

>>> fn = resolve_variable("json:dumps", expected_type=type(lambda: None))
>>> callable(fn)
True
"""

from __future__ import annotations

from importlib import import_module
from typing import TypeVar

T = TypeVar("T")

#: Known third-party packages that the SDK frequently resolves
#: classes from.  Used to translate a missing transitive
#: dependency into an actionable install hint.
MODULE_TO_PACKAGE_HINTS: dict[str, str] = {
    "langchain_google_genai": "langchain-google-genai",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_openai": "langchain-openai",
    "langchain_deepseek": "langchain-deepseek",
    "langchain_mistralai": "langchain-mistralai",
    "langchain_fireworks": "langchain-fireworks",
    "langchain_groq": "langchain-groq",
    "langchain_cohere": "langchain-cohere",
    "langchain_aws": "langchain-aws",
    "langchain_community": "langchain-community",
    "langfuse": "langfuse",
}


def _build_missing_dependency_hint(module_path: str, err: ImportError) -> str:
    """Build an actionable hint when a module import fails.

    The in-tree reference prefers the provider package hint for
    known integrations, even when the import error is triggered
    by a transitive dependency (e.g. ``google`` from
    ``langchain_google_genai``).  We keep the same logic and
    extend ``MODULE_TO_PACKAGE_HINTS`` with a small set of
    additional langchain integrations.
    """
    module_root = module_path.split(".", 1)[0]
    missing_module = getattr(err, "name", None) or module_root

    # Prefer provider package hints for known integrations, even
    # when the import error is triggered by a transitive
    # dependency.
    package_name = MODULE_TO_PACKAGE_HINTS.get(module_root)
    if package_name is None:
        package_name = MODULE_TO_PACKAGE_HINTS.get(missing_module, missing_module.replace("_", "-"))

    return f"Missing dependency '{missing_module}'. Install it with `uv add {package_name}` (or `pip install {package_name}`), then restart the application."


def resolve_variable(
    variable_path: str,
    expected_type: type[T] | tuple[type, ...] | None = None,
) -> T:
    """Resolve any variable from a ``"module.path:attribute"`` path.

    Args:
        variable_path: The path to the variable, in the form
            ``"parent_package.sub_package.module:attribute"``.
        expected_type: Optional type or tuple of types to
            validate the resolved variable against.  When
            provided, :func:`isinstance` is used to check the
            resolved value.

    Returns:
        The resolved variable.

    Raises:
        ImportError: If the module path is invalid (no
            ``:`` separator), the module cannot be imported, or
            the attribute does not exist on the module.  The
            error message includes an actionable install hint
            when the failure is a missing optional dependency.
        ValueError: If *expected_type* is provided and the
            resolved variable is not an instance of that type.
    """
    try:
        module_path, variable_name = variable_path.rsplit(":", 1)
    except ValueError as err:
        raise ImportError(
            f"{variable_path!r} doesn't look like a variable path. "
            "Example: parent_package.sub_package.module:variable_name"
        ) from err

    try:
        module = import_module(module_path)
    except ImportError as err:
        module_root = module_path.split(".", 1)[0]
        err_name = getattr(err, "name", None)
        if isinstance(err, ModuleNotFoundError) or err_name == module_root:
            hint = _build_missing_dependency_hint(module_path, err)
            raise ImportError(f"Could not import module {module_path!r}. {hint}") from err
        # Preserve the original ImportError message for non-missing-module failures.
        raise ImportError(f"Error importing module {module_path!r}: {err}") from err

    try:
        variable = getattr(module, variable_name)
    except AttributeError as err:
        raise ImportError(f"Module {module_path!r} does not define a {variable_name!r} attribute/class") from err

    # Type validation
    if expected_type is not None and not isinstance(variable, expected_type):
        if isinstance(expected_type, type):
            type_name = expected_type.__name__
        else:
            type_name = " or ".join(t.__name__ for t in expected_type)
        raise ValueError(f"{variable_path!r} is not an instance of {type_name}, got {type(variable).__name__}")

    return variable


def resolve_class(class_path: str, base_class: type[T] | None = None) -> type[T]:
    """Resolve a class from a ``"module.path:ClassName"`` path.

    Args:
        class_path: The path to the class.
        base_class: Optional base class.  When provided, the
            resolved class must be a strict subclass of this
            base.

    Returns:
        The resolved class.

    Raises:
        ImportError: If the module path is invalid, the module
            cannot be imported, or the attribute does not
            exist.  See :func:`resolve_variable` for the error
            contract.
        ValueError: If the resolved object is not a class, or
            (when *base_class* is supplied) is not a subclass
            of *base_class*.
    """
    cls = resolve_variable(class_path, expected_type=type)

    if not isinstance(cls, type):
        raise ValueError(f"{class_path!r} is not a valid class")

    if base_class is not None and not issubclass(cls, base_class):
        raise ValueError(f"{class_path!r} is not a subclass of {base_class.__name__}")

    return cls
