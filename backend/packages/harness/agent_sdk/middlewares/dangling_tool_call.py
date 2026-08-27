"""DanglingToolCallMiddleware — patch missing tool results before model call.

When a run is interrupted or cancelled, the message history
may end up with an :class:`AIMessage` whose ``tool_calls``
list references :class:`ToolMessage` IDs that do not exist in
the history. The next model call will reject this
malformed conversation with a provider error.

This middleware scans the message history just before the
model call and, for every ``AIMessage`` whose tool calls are
missing a corresponding :class:`ToolMessage`, injects a
synthetic error :class:`ToolMessage` *immediately after* the
offending ``AIMessage``. The patches are inserted in-place
(not appended) so the position is correct in the sequence.

The middleware uses ``wrap_model_call`` rather than
``before_model`` because langgraph's ``add_messages``
reducer, combined with ``before_model`` return values, would
otherwise append the patches to the *end* of the message list
— which is not the right place for a per-AIMessage fix-up.

**Brand-neutral**: this middleware is pure infrastructure.
It is part of the SDK's always-on chain.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Insert placeholder :class:`ToolMessage`\\ s for dangling tool calls.

    A "dangling" tool call is one whose ``id`` appears in an
    :class:`AIMessage` ``tool_calls`` list but has no matching
    :class:`ToolMessage` anywhere later in the history. The
    middleware injects a synthetic error :class:`ToolMessage`
    immediately after each offending ``AIMessage`` so the
    conversation stays well-formed for the next model call.
    """

    @staticmethod
    def _message_tool_calls(msg: Any) -> list[dict]:
        """Return normalised tool calls from an :class:`AIMessage`.

        Handles two shapes:
        * ``msg.tool_calls`` populated (langchain style);
        * ``msg.additional_kwargs["tool_calls"]`` populated
          (some providers serialise tool calls under that
          legacy key).

        Returns a list of ``{id, name, args}`` dicts. Items
        with no parseable name are dropped.
        """
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            return list(tool_calls)

        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        normalised: list[dict] = []
        for raw_tc in raw_tool_calls:
            if not isinstance(raw_tc, dict):
                continue

            function = raw_tc.get("function")
            name = raw_tc.get("name")
            if not name and isinstance(function, dict):
                name = function.get("name")

            args = raw_tc.get("args", {})
            if not args and isinstance(function, dict):
                raw_args = function.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed_args = {}
                    args = parsed_args if isinstance(parsed_args, dict) else {}

            normalised.append(
                {
                    "id": raw_tc.get("id"),
                    "name": name or "unknown",
                    "args": args if isinstance(args, dict) else {},
                }
            )

        return normalised

    def _build_patched_messages(self, messages: list[Any]) -> list | None:
        """Return a new message list with dangling messages fixed.

        Three complementary checks:

        1. **Orphaned ToolMessages** — a ToolMessage whose
           ``tool_call_id`` has no matching AIMessage(tool_calls)
           anywhere in the list.  These are **removed**; they would
           cause the provider to reject the request with 400.

        2. **Dangling tool calls** — an AIMessage whose
           ``tool_calls`` reference ToolMessages that don't exist.
           A synthetic error ToolMessage is **inserted** immediately
           after each offending AIMessage.

        3. **Tool-call contiguity** — when a non-tool message
           (e.g. a ``[LOOP DETECTED]`` HumanMessage injected by
           :class:`LoopDetectionMiddleware`) appears between an
           AIMessage(tool_calls) and its ToolMessages, the
           ToolMessages are **relocated** to immediately follow the
           AIMessage. DeepSeek and other strict providers reject
           AIMessage(tool_calls) when ToolMessages are not contiguous.

        Returns ``None`` if no patches are needed.
        """
        # ── Collect tool_call_ids from AIMessage tool_calls ────────────
        existing_ai_tool_call_ids: set[str] = set()
        for msg in messages:
            if getattr(msg, "type", None) == "ai":
                for tc in self._message_tool_calls(msg):
                    tc_id = tc.get("id")
                    if tc_id:
                        existing_ai_tool_call_ids.add(tc_id)

        # ── Detect orphaned ToolMessages ───────────────────────────────
        orphaned_tool_msg_indices: set[int] = set()
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                if msg.tool_call_id not in existing_ai_tool_call_ids:
                    orphaned_tool_msg_indices.add(i)

        # ── Detect dangling AIMessage tool calls (original logic) ──────
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        needs_dangle_patch = False
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    needs_dangle_patch = True
                    break
            if needs_dangle_patch:
                break

        if not orphaned_tool_msg_indices and not needs_dangle_patch:
            return None

        # ── Build patched list ─────────────────────────────────────────
        # Start with orphan-removed messages, then insert dangling patches.
        if orphaned_tool_msg_indices:
            _orphan_ids = [messages[i].tool_call_id for i in orphaned_tool_msg_indices]
            logger.warning(
                "Removing %d orphaned ToolMessage(s) with no preceding tool_calls: %s",
                len(orphaned_tool_msg_indices), _orphan_ids,
            )

        # Rebuild the list with orphans actually removed.
        patched = [m for i, m in enumerate(messages) if i not in orphaned_tool_msg_indices]

        # Rebuild existing_tool_msg_ids from the cleaned list so the
        # dangling detection below doesn't double-count messages that
        # were already removed.
        existing_tool_msg_ids.clear()
        for msg in patched:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        needs_dangle_patch = False
        for msg in patched:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    needs_dangle_patch = True
                    break
            if needs_dangle_patch:
                break

        if not needs_dangle_patch:
            return self._ensure_contiguity(patched)

        # ── Insert synthetic ToolMessages for dangling tool calls ────
        result: list = []
        patched_ids: set[str] = set()
        patch_count = 0
        for msg in patched:
            result.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids and tc_id not in patched_ids:
                    result.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patched_ids.add(tc_id)
                    patch_count += 1

        if patch_count:
            logger.warning(
                "Injecting %d placeholder ToolMessage(s) for dangling tool calls: %s",
                patch_count, list(patched_ids),
            )

        return self._ensure_contiguity(result)

    def _ensure_contiguity(self, messages: list[Any]) -> list[Any]:
        """Reorder messages so ToolMessages are contiguous with their AIMessage.

        Some providers (DeepSeek, MiniMax) reject requests where a non-tool
        message (e.g. a ``[LOOP DETECTED]`` HumanMessage injected by
        :class:`LoopDetectionMiddleware`) appears between an
        AIMessage(tool_calls) and its ToolMessages.

        This method detects separated tool-call pairs and moves all matching
        ToolMessages to immediately follow their owning AIMessage.
        """
        # ── Collect AIMessage → tool_call_ids mapping ─────────────────
        ai_tool_call_ids: dict[int, set[str]] = {}
        for i, msg in enumerate(messages):
            if getattr(msg, "type", None) == "ai":
                tc_ids: set[str] = set()
                for tc in self._message_tool_calls(msg):
                    tc_id = tc.get("id")
                    if tc_id:
                        tc_ids.add(tc_id)
                if tc_ids:
                    ai_tool_call_ids[i] = tc_ids

        if not ai_tool_call_ids:
            return messages

        # ── Build tool_call_id → owner AI index lookup ───────────────
        tc_to_ai: dict[str, int] = {}
        for ai_idx, tc_ids in ai_tool_call_ids.items():
            for tc_id in tc_ids:
                tc_to_ai[tc_id] = ai_idx

        # ── Check if any ToolMessage is separated from its AI owner ──
        needs_reorder = False
        separated_ids: list[str] = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                ai_idx = tc_to_ai.get(msg.tool_call_id)
                if ai_idx is not None:
                    for j in range(ai_idx + 1, i):
                        if not isinstance(messages[j], ToolMessage):
                            needs_reorder = True
                            separated_ids.append(msg.tool_call_id)
                            break

        if not needs_reorder:
            return messages

        logger.warning(
            "Reordering %d ToolMessage(s) for tool-call contiguity: %s",
            len(separated_ids), separated_ids,
        )

        # ── Rebuild: ToolMessages follow their AI immediately ────────
        result: list[Any] = []
        moved: set[int] = set()

        for i, msg in enumerate(messages):
            if i in moved:
                continue

            result.append(msg)

            if i in ai_tool_call_ids:
                tc_ids = ai_tool_call_ids[i]
                for j in range(i + 1, len(messages)):
                    mj = messages[j]
                    if j not in moved and isinstance(mj, ToolMessage) and mj.tool_call_id in tc_ids:
                        result.append(mj)
                        moved.add(j)

        return result

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
