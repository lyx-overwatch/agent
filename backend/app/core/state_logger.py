"""State logger — persist full agent state as JSON for debugging / forensics.

Organises logs as ``backend/logs/{conversation_id}/`` with one JSON file
per agent execution (timestamped).  Each file contains:

* ``conversation_id``
* ``thread_id``
* ``timestamp``
* ``request`` — the user's input message
* ``state_before`` — agent state snapshot BEFORE this run
* ``state_after`` — agent state snapshot AFTER this run
* ``error`` — exception info if the run failed
* ``recursion_limit`` — the limit in effect for this run
* ``total_steps`` — approximate step count (message delta)

Messages are serialised to plain dicts so the JSON is compact and
human-readable in any editor.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Re-export from the SDK shared module so callers only need one import.
from agent_sdk.middlewares.state_logger import (  # noqa: F401
    collect_model_call,
    get_model_calls,
    reset_model_calls,
)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

# ── Config ──────────────────────────────────────────────────────────────────
_LOGS_ROOT = Path(__file__).resolve().parent.parent.parent / "logs"
_MAX_LOG_FILES_PER_CONVERSATION = 20  # keep at most N files per conversation_id
_MAX_STATE_CHARS = 2_000_000  # hard cap on serialised state (2 MB)


def _serialize_message(msg: BaseMessage) -> dict[str, Any]:
    """Convert a LangChain message to a plain JSON-safe dict."""
    out: dict[str, Any] = {
        "type": getattr(msg, "type", type(msg).__name__),
        "id": getattr(msg, "id", None),
    }

    # Content
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        out["content"] = content
    elif isinstance(content, list):
        out["content"] = [str(block) for block in content]
    elif content is not None:
        out["content"] = str(content)

    # Extra fields per message type
    if isinstance(msg, AIMessage):
        tc = getattr(msg, "tool_calls", None)
        if tc:
            out["tool_calls"] = [
                {
                    "id": t.get("id"),
                    "name": t.get("name", "?"),
                    "args": t.get("args", {}),
                }
                for t in tc
            ]
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            out["usage_metadata"] = dict(usage)

    if isinstance(msg, ToolMessage):
        out["tool_call_id"] = getattr(msg, "tool_call_id", None)
        out["name"] = getattr(msg, "name", None)

    if isinstance(msg, HumanMessage):
        name = getattr(msg, "name", None)
        if name:
            out["name"] = name

    if isinstance(msg, SystemMessage):
        pass  # content already captured

    return out


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert agent state to a JSON-safe dict.

    The ``messages`` list is the main payload; all other top-level
    keys are kept as-is (they are simple scalars / small dicts).
    """
    out: dict[str, Any] = {}
    for key, val in state.items():
        if key == "messages":
            out["messages"] = [_serialize_message(m) for m in val]
        elif isinstance(val, (str, int, float, bool, type(None))):
            out[key] = val
        elif isinstance(val, dict):
            out[key] = {str(k): str(v) for k, v in val.items()}
        elif isinstance(val, list):
            out[key] = [str(v) for v in val]
        else:
            out[key] = str(val)
    return out


def _safe_name(raw: str) -> str:
    """Sanitize a user / conversation identifier for use as a directory name."""
    return raw.replace("\\", "_").replace("/", "_").replace(":", "_")


def _ensure_conversation_dir(conversation_id: str, *, user_id: str | None = None) -> Path:
    """Create (if needed) and return the per-conversation directory.

    When *user_id* is given the layout is ``logs/{user_id}/{conversation_id}/``;
    otherwise it falls back to ``logs/{conversation_id}/`` for backward
    compatibility with older state logs.
    """
    if user_id:
        d = _LOGS_ROOT / _safe_name(user_id) / _safe_name(conversation_id)
    else:
        d = _LOGS_ROOT / _safe_name(conversation_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rotate_old_logs(conv_dir: Path) -> None:
    """Remove oldest log files if the per-conversation cap is exceeded."""
    try:
        files = sorted(conv_dir.glob("*.json"), key=os.path.getmtime)
        while len(files) > _MAX_LOG_FILES_PER_CONVERSATION:
            oldest = files.pop(0)
            oldest.unlink()
            logger.debug("Rotated old state log: {}", oldest)
    except Exception:
        pass


# ── Public API ──────────────────────────────────────────────────────────────


def save_state_log(
    *,
    conversation_id: str,
    thread_id: str,
    user_message: str,
    state_before: dict[str, Any] | None = None,
    state_after: dict[str, Any] | None = None,
    error: BaseException | None = None,
    recursion_limit: int | None = None,
    model_id: str = "",
    user_id: str | None = None,
    model_calls: list[dict[str, Any]] | None = None,
) -> Path | None:
    """Persist agent state snapshots to disk.

    Args:
        conversation_id: The business-level conversation id (UUID).
        thread_id: The LangGraph thread id.
        user_message: The user's input text for this turn.
        state_before: Agent state BEFORE the run (or ``None``).
        state_after: Agent state AFTER the run (or ``None``).
        error: The exception if the run failed (or ``None``).
        recursion_limit: The ``recursion_limit`` in effect.
        model_id: The model id string.
        user_id: Optional user id for per-user grouping under
            ``logs/{user_id}/{conversation_id}/``.
        model_calls: Optional list of model-call summaries collected
            during agent execution (from :func:`collect_model_call`).

    Returns:
        Path to the written file, or ``None`` if writing failed.
    """
    try:
        conv_dir = _ensure_conversation_dir(conversation_id, user_id=user_id)
        _rotate_old_logs(conv_dir)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = conv_dir / f"{timestamp}.json"

        # Count approximate steps (message deltas)
        before_count = len(state_before.get("messages", [])) if state_before else 0
        after_count = len(state_after.get("messages", [])) if state_after else 0

        doc: dict[str, Any] = {
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "timestamp": timestamp,
            "model_id": model_id,
            "recursion_limit": recursion_limit,
            "request": user_message,
            "steps_estimate": max(0, after_count - before_count),
            "state_before": _serialize_state(state_before) if state_before else None,
            "state_after": _serialize_state(state_after) if state_after else None,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            } if error else None,
        }

        # ── Message integrity diagnostics ───────────────────────────────
        # Run on the serialised state_after.messages when there is an error,
        # so forensics can spot orphaned ToolMessages / dangling tool_calls
        # without having to manually trawl the full message list.
        if error is not None and doc.get("state_after") and isinstance(doc["state_after"], dict):
            _serialised_msgs = doc["state_after"].get("messages", [])
            if _serialised_msgs:
                doc["diagnostics"] = _diagnose_messages(_serialised_msgs)

        # ── Model call summaries ────────────────────────────────────────
        if model_calls:
            doc["model_calls"] = model_calls

        raw = json.dumps(doc, ensure_ascii=False, indent=2)
        if len(raw) > _MAX_STATE_CHARS:
            # Truncate state sections to stay under the cap
            doc["state_before"] = _truncate_state(doc["state_before"], _MAX_STATE_CHARS // 2)
            doc["state_after"] = _truncate_state(doc["state_after"], _MAX_STATE_CHARS // 2)
            raw = json.dumps(doc, ensure_ascii=False, indent=2)

        filename.write_text(raw, encoding="utf-8")
        logger.info(
            "State log saved: {} (conversation={}, thread={}, msgs_before={}, msgs_after={}, error={})",
            filename.name, conversation_id, thread_id, before_count, after_count, type(error).__name__ if error else "none",
        )
        return filename
    except Exception:
        logger.exception("Failed to save state log for conversation {}", conversation_id)
        return None


def _diagnose_messages(messages: list[dict]) -> dict[str, Any]:
    """Analyze serialised messages for integrity issues that can cause API errors.

    Returns a dict with:
    - ``total``: total message count
    - ``tool_messages``: count of ToolMessage entries
    - ``ai_with_tool_calls``: count of AIMessage entries that have tool_calls
    - ``orphaned_tool_messages``: ToolMessages whose tool_call_id has no matching
      preceding AIMessage(tool_calls) — these will cause a 400 error
    - ``dangling_tool_calls``: tool_calls from AIMessages that have no matching
      ToolMessage — the model may see a tool call it never made
    - ``pairing_summary``: human-readable summary of the pairing state
    """
    # Collect all tool_call_ids declared by AIMessages
    ai_tool_call_ids: set[str] = set()
    ai_with_tool_calls_count = 0
    for msg in messages:
        if msg.get("type") == "ai":
            tcs = msg.get("tool_calls")
            if tcs:
                ai_with_tool_calls_count += 1
                for tc in tcs:
                    tc_id = tc.get("id")
                    if tc_id:
                        ai_tool_call_ids.add(tc_id)

    # Collect all tool_call_ids from ToolMessages
    tool_msg_count = 0
    tool_msg_ids: set[str] = set()
    for msg in messages:
        if msg.get("type") == "tool":
            tool_msg_count += 1
            tc_id = msg.get("tool_call_id")
            if tc_id:
                tool_msg_ids.add(tc_id)

    orphaned_tool_messages = tool_msg_ids - ai_tool_call_ids
    dangling_tool_calls = ai_tool_call_ids - tool_msg_ids

    total_tool_call_pairs = len(ai_tool_call_ids & tool_msg_ids)

    parts: list[str] = []
    if orphaned_tool_messages:
        parts.append(f"{len(orphaned_tool_messages)} orphaned ToolMessage(s): {sorted(orphaned_tool_messages)}")
    if dangling_tool_calls:
        parts.append(f"{len(dangling_tool_calls)} dangling tool_call(s): {sorted(dangling_tool_calls)}")

    return {
        "total_messages": len(messages),
        "tool_messages": tool_msg_count,
        "ai_with_tool_calls": ai_with_tool_calls_count,
        "tool_call_pairs_healthy": total_tool_call_pairs,
        "orphaned_tool_messages": sorted(orphaned_tool_messages),
        "dangling_tool_calls": sorted(dangling_tool_calls),
        "summary": "OK" if not parts else "; ".join(parts),
    }


def _truncate_state(state_section: dict | None, max_chars: int) -> dict | None:
    """Truncate the messages list in a serialised state section."""
    if state_section is None:
        return None
    msgs = state_section.get("messages", [])
    total = 0
    kept = []
    for m in msgs:
        chunk = len(json.dumps(m, ensure_ascii=False))
        if total + chunk > max_chars:
            kept.append({"_truncated": True, "omitted_count": len(msgs) - len(kept)})
            break
        kept.append(m)
        total += chunk
    return {**state_section, "messages": kept}


def get_logs_dir(*, user_id: str | None = None) -> Path:
    """Return the absolute path to the logs root, or to a per-user sub-directory."""
    base = _LOGS_ROOT.resolve()
    if user_id:
        return base / _safe_name(user_id)
    return base


def delete_conversation_logs(conversation_id: str, *, user_id: str | None = None) -> bool:
    """Remove all state log files for a specific conversation.

    Returns ``True`` if the directory was removed, ``False`` if it didn't exist.
    """
    if user_id:
        d = _LOGS_ROOT / _safe_name(user_id) / _safe_name(conversation_id)
    else:
        d = _LOGS_ROOT / _safe_name(conversation_id)
    if not d.exists():
        return False
    import shutil
    shutil.rmtree(d)
    logger.info("Deleted state logs for conversation {} (user={})", conversation_id, user_id or "-")
    return True


def cleanup_old_logs(max_age_days: int = 7) -> int:
    """Remove log directories older than *max_age_days*.

    Handles both the flat ``logs/{conversation_id}/`` layout (legacy) and
    the two-level ``logs/{user_id}/{conversation_id}/`` layout.

    Returns the number of directories removed.
    """
    if not _LOGS_ROOT.exists():
        return 0
    cutoff = datetime.now(UTC).timestamp() - max_age_days * 86400
    removed = 0
    for entry in _LOGS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        try:
            # Two-level layout: entry is a user directory
            if any(e.is_dir() for e in entry.iterdir()):
                for conv_dir in entry.iterdir():
                    if conv_dir.is_dir():
                        try:
                            if os.path.getmtime(conv_dir) < cutoff:
                                import shutil
                                shutil.rmtree(conv_dir)
                                removed += 1
                        except Exception:
                            pass
                # Clean up empty user directories
                if not any(entry.iterdir()):
                    entry.rmdir()
            else:
                # Flat legacy layout: entry is itself a conversation directory
                if os.path.getmtime(entry) < cutoff:
                    import shutil
                    shutil.rmtree(entry)
                    removed += 1
        except Exception:
            pass
    return removed