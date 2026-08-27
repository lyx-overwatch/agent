"""LangGraph integration helpers.

This module is a re-implementation (per ADR-010) of the small
brand-neutral glue that the SDK needs to wire a chat model,
tools, middlewares, state, and a checkpointer into a
:class:`langgraph.graph.state.CompiledStateGraph`.  It does
**not** re-implement LangGraph — it provides thin, well-named
helpers on top of the standard langgraph / langchain APIs so
the rest of the SDK (and any product built on it) can stay
free of inline ``{"configurable": {...}}`` boilerplate.

The helpers are deliberately tiny — anything that requires
business knowledge (DeerFlow's specific thread-id shape, the
default model, the default checkpointer) lives in the
:mod:`agent_sdk.presets.deerflow` package, not here.
"""

from __future__ import annotations

import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Configurable key constants
# ---------------------------------------------------------------------------

#: Standard LangGraph configurable key for the thread id.
#: Equivalent to ``"thread_id"`` in the LangGraph docs.
THREAD_ID: str = "thread_id"

#: Standard LangGraph configurable key for the user id.
#: Read by langgraph's ``get_store`` helpers and by LangGraph
#: Platform's access-control layer.
USER_ID: str = "user_id"

#: Configurable key for the agent / run id, used by run
#: managers that need to track multiple concurrent runs
#: against the same thread.
RUN_ID: str = "run_id"

#: Configurable key for the checkpoint namespace.  LangGraph
#: uses this to scope checkpoints (e.g. per-user or per-run
#: subgraphs).
CHECKPOINT_NS: str = "checkpoint_ns"


# ---------------------------------------------------------------------------
# RunnableConfig builders
# ---------------------------------------------------------------------------


def make_thread_config(
    thread_id: str,
    *,
    user_id: str | None = None,
    run_id: str | None = None,
    checkpoint_ns: str = "",
) -> dict[str, Any]:
    """Build a ``RunnableConfig`` dict for *thread_id*.

    This is the most common shape used by langgraph primitives
    that take a ``config=`` argument (e.g. ``graph.invoke``,
    ``graph.stream``, ``graph.astream_events``).

    Args:
        thread_id: Stable identifier of the conversation
            thread.  Must be unique per user.
        user_id: Optional identifier of the authenticated
            user.  Pass when the runtime uses LangGraph
            Platform's access-control layer.
        run_id: Optional identifier of the current run
            (use :func:`make_run_id` to mint one).
        checkpoint_ns: Optional checkpoint namespace
            (default: ``""`` — the default namespace).

    Returns:
        A dict of the form
        ``{"configurable": {"thread_id": ..., ...}}`` ready
        to be passed as the ``config=`` argument of a
        LangGraph primitive.
    """
    configurable: dict[str, Any] = {THREAD_ID: thread_id, CHECKPOINT_NS: checkpoint_ns}
    if user_id is not None:
        configurable[USER_ID] = user_id
    if run_id is not None:
        configurable[RUN_ID] = run_id
    return {"configurable": configurable}


def merge_configs(*configs: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple ``RunnableConfig`` dicts.

    ``configurable`` entries are merged by key (later
    overrides earlier); non-configurable top-level keys are
    kept as-is.  This is useful when a caller wants to add a
    ``thread_id`` to a config that already carries, e.g.,
    custom ``metadata``.

    Args:
        *configs: One or more ``RunnableConfig`` dicts.

    Returns:
        A new dict with the merged configuration.
    """
    merged: dict[str, Any] = {}
    configurable: dict[str, Any] = {}
    for cfg in configs:
        if not cfg:
            continue
        for key, value in cfg.items():
            if key == "configurable" and isinstance(value, dict):
                configurable.update(value)
            else:
                merged[key] = value
    if configurable:
        merged["configurable"] = configurable
    return merged


# ---------------------------------------------------------------------------
# Run id helpers
# ---------------------------------------------------------------------------


def make_run_id() -> str:
    """Mint a fresh, URL-safe run id.

    The default is a UUID4 hex string — a sensible default
    that round-trips through ``Last-Event-ID`` HTTP headers
    and JSON serialisation without escaping.  Presets that
    need a different scheme (short ids, prefixed ids) can
    override this; the SDK does not assume any particular
    format.
    """
    return uuid.uuid4().hex


def is_valid_thread_id(thread_id: str) -> bool:
    """Return ``True`` if *thread_id* is safe to use as a path component.

    LangGraph does not constrain thread ids, but the runtime
    uses them as filesystem path components in the per-thread
    workspace.  This helper enforces the conservative subset
    the SDK uses everywhere:

    * non-empty
    * at most 128 characters
    * made up of letters, digits, dashes, and underscores

    Any other character set is rejected because it would
    require additional escaping when threaded through
    shell tools or path joins. Dots are rejected to match
    the backend's ``deerflow.config.paths._validate_thread_id``
    regex (``^[A-Za-z0-9_-]+$``) — a thread_id that
    crosses the SDK/backend persistence boundary must
    validate on both sides.
    """
    if not thread_id or len(thread_id) > 128:
        return False
    return all(c.isalnum() or c in "-_" for c in thread_id)


# ---------------------------------------------------------------------------
# Stream mode constants
# ---------------------------------------------------------------------------

#: Standard LangGraph stream mode names, re-exported here so
#: callers do not need a second import.
STREAM_MODE_VALUES: tuple[str, ...] = ("values", "updates", "messages", "events", "custom")

#: Stream mode that carries per-node state updates.
STREAM_MODE_UPDATES: str = "updates"

#: Stream mode that carries LLM token messages.
STREAM_MODE_MESSAGES: str = "messages"

#: Stream mode that carries the full state snapshot at each step.
STREAM_MODE_VALUES_DEFAULT: str = "values"
