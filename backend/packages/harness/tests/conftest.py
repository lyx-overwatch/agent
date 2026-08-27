"""Pytest configuration shared across the SDK test suite.

Notes (per ADR-010):
    The SDK test suite MUST NOT import anything from ``backend.*``.
    This conftest enforces that by clearing ``sys.path`` for the
    duration of test collection. The fixtures here are pure-Python
    and self-contained.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the SDK package is importable as ``agent_sdk`` without
# requiring the test runner to set PYTHONPATH manually.
SDK_ROOT = Path(__file__).resolve().parents[1]
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

# Block any accidental import of the backend package from the SDK
# test suite. If a test ever tries ``from deerflow.* import ...`` or
# ``from backend.* import ...`` the import will fail and the test
# will be reported as a failure with a clear error.
_BLOCKED_PREFIXES = ("deerflow", "backend", "app")


class _ImportBlocker:
    """Meta-path finder that raises on any import under a blocked prefix."""

    def find_module(self, name: str, path=None):  # type: ignore[override]
        for prefix in _BLOCKED_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                raise ImportError(
                    f"SDK tests must not import {name!r}. "
                    "Per ADR-010 the SDK is re-implemented from scratch "
                    "and never imports from backend/deerflow/app."
                )
        return None


sys.meta_path.insert(0, _ImportBlocker())
