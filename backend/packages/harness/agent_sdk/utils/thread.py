"""Shared thread-resolution helpers used by multiple subsystems.

These tiny helpers were duplicated across :mod:`agent_sdk.sandbox.tools`,
:mod:`agent_sdk.sandbox.path_resolver`, :mod:`agent_sdk.sandbox.middleware`,
and :mod:`agent_sdk.middlewares.summarization`.  Centralising them here
avoids drift between the copies.

All functions are pure and dependency-free — they only touch stdlib
and (for the langgraph helper) an optional import that catches gracefully.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.runtime import Runtime


def extract_thread_id(thread_data: dict | None) -> str | None:
    """Extract ``thread_id`` from *thread_data* by inspecting ``workspace_path``.

    Uses a regex to locate the ``/threads/{thread_id}/`` segment in the
    workspace path. This is robust to any ancestor directory depth —
    works with both the flat layout (``{base}/threads/{tid}/workspace``)
    and the multi-user layout (``{base}/users/{uid}/threads/{tid}/workspace``).

    The regex accepts both forward-slash (POSIX) and backslash (Windows)
    path separators.

    Returns ``None`` when *thread_data* is missing or has no
    ``workspace_path``.
    """
    if thread_data is None:
        return None
    workspace_path = thread_data.get("workspace_path")
    if not workspace_path:
        return None
    import re

    # Accept both / and \\ as path separators — the SDK runs on
    # both Windows (local dev) and Linux (production / Docker).
    m = re.search(r"[/\\]threads[/\\]([^/\\]+)[/\\]", workspace_path)
    return m.group(1) if m else None


def resolve_thread_id(runtime: Runtime | None) -> str | None:
    """Resolve the current thread id from *runtime* or the langgraph config.

    Priority order:
    1. ``runtime.context["thread_id"]`` (set by the middleware chain)
    2. ``langgraph.config.get_config()["configurable"]["thread_id"]``

    Returns ``None`` when neither source has a thread id, or when
    the langgraph config is not available (outside a run context).
    """
    if runtime is not None and runtime.context is not None:
        tid = runtime.context.get("thread_id")
        if tid is not None:
            return tid
    try:
        from langgraph.config import get_config

        cfg = get_config()
    except RuntimeError:
        return None
    return cfg.get("configurable", {}).get("thread_id")


__all__ = [
    "extract_thread_id",
    "resolve_thread_id",
]
