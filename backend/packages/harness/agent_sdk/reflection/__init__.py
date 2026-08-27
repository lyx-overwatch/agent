"""Reflection utilities for resolving classes and variables from string paths.

This module is a re-implementation (per ADR-010) of
``deerflow.reflection``.  It provides two generic helpers:

* :func:`resolve_variable` — load any Python object from a
  ``"module.path:attribute"`` string, with optional
  ``isinstance`` validation and actionable import-error hints.
* :func:`resolve_class` — same idea, but for a class, with an
  optional ``issubclass`` check.

Why this exists
---------------
The SDK and the DeerFlow preset both use string paths to
reference classes (model providers, tool factories, …) so that
configuration is fully declarative.
This module centralises the *resolution* side of that contract
and produces user-friendly error messages when a package is
missing — the in-tree reference's
``_build_missing_dependency_hint`` is preserved here with the
same set of known integration packages.
"""

from agent_sdk.reflection.resolvers import resolve_class, resolve_variable

__all__ = ["resolve_class", "resolve_variable"]
