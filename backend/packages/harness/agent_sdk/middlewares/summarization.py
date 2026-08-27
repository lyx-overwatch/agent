"""SummarizationMiddleware — drop old messages once a token budget is hit.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.summarization_middleware``.

The middleware:

* counts the tokens of the current message list;
* when the count exceeds ``max_tokens_before_summary``,
  splits the list at the cutoff index, summarises the
  older half with the configured model, and replaces the
  older messages with a single ``HumanMessage(name="summary")``
  carrying the summary text;
* fires any caller-registered
  :class:`BeforeSummarizationHook` callbacks **before** the
  messages are removed, so telemetry / journaling code can
  record what was about to be discarded;
* supports an optional *skill-rescue* step (via the
  ``message_partitioner`` callable) that lets a product
  keep a few recent "skill load" tool calls out of the
  summary — useful when a tool reads a long SKILL.md and
  the next turn still needs it.

The base summarization algorithm follows the in-tree
reference: a configurable trigger (``tokens`` /
``messages``), a ``keep`` policy (default: 20 most recent
messages), and a summary prompt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from agent_sdk.utils.thread import resolve_thread_id

logger = logging.getLogger(__name__)


#: Default summary-prompt template. Brand-neutral (no
#: product-specific structure).
DEFAULT_SUMMARY_PROMPT: str = (
    "Please summarise the following conversation so far. "
    "Keep the summary concise but retain any information that "
    "would be needed to continue the conversation.\n\n"
    "<messages>\n{messages}\n</messages>"
)


@dataclass(frozen=True)
class SummarizationEvent:
    """Context emitted before conversation history is summarised.

    Hooks are passed this event; they can inspect what is
    about to be summarised and what will be preserved.
    """

    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    thread_id: str | None
    agent_name: str | None


@runtime_checkable
class BeforeSummarizationHook(Protocol):
    """Hook invoked before summarisation removes messages from state."""

    def __call__(self, event: SummarizationEvent) -> None: ...


# ---------------------------------------------------------------------------
# Message partitioners
# ---------------------------------------------------------------------------


def default_partitioner(
    messages: list[AnyMessage],
    cutoff_index: int,
) -> tuple[list[AnyMessage], list[AnyMessage]]:
    """Split *messages* at *cutoff_index* into (to_summarise, preserved).

    Protects tool-call pairs from being split: if a ToolMessage in the
    preserved half has its corresponding AIMessage(tool_calls) in the
    to-summarise half, that AIMessage is moved into preserved so the
    model always receives a well-formed conversation — every ``tool``
    role message is preceded by an ``assistant`` message with the
    matching ``tool_calls`` field.

    A rescued AIMessage may issue *multiple* tool calls.  Any of its
    ToolMessages that still live in the to-summarise half are moved
    along with it — otherwise summarising the older half would leave a
    dangling tool call, which strict providers reject (and the
    :class:`DanglingToolCallMiddleware` then has to paper over).
    """
    to_summarize = list(messages[:cutoff_index])
    preserved = list(messages[cutoff_index:])

    # ── Protect tool-call pairs ───────────────────────────────────────
    # Collect tool_call_ids owned by preserved ToolMessages.
    _preserved_tool_msg_ids: set[str] = set()
    for msg in preserved:
        if isinstance(msg, ToolMessage):
            _preserved_tool_msg_ids.add(str(msg.tool_call_id))

    if not _preserved_tool_msg_ids:
        return to_summarize, preserved

    # Find AIMessages in to_summarize whose tool_calls reference any
    # preserved ToolMessage — these must be rescued so the ToolMessage
    # stays paired with its owning AIMessage.  While scanning, also
    # record *every* tool_call_id owned by a rescued AIMessage: the ones
    # whose ToolMessage is still in the to-summarise half must be moved
    # along too (see below).
    _orphan_ai_indices: set[int] = set()
    _rescued_ai_tool_call_ids: set[str] = set()
    for i, msg in enumerate(to_summarize):
        if not isinstance(msg, AIMessage):
            continue
        _tool_calls = getattr(msg, "tool_calls", None) or []
        _tc_ids: set[str] = set()
        for tc in _tool_calls:
            _tc_id = str(tc.get("id", ""))
            if _tc_id:
                _tc_ids.add(_tc_id)
        if _tc_ids & _preserved_tool_msg_ids:
            _orphan_ai_indices.add(i)
            _rescued_ai_tool_call_ids.update(_tc_ids)

    if not _orphan_ai_indices:
        return to_summarize, preserved

    # Rescue any ToolMessage still in the to-summarise half that belongs
    # to a rescued AIMessage.  Without this, a multi-tool-call AIMessage
    # whose other result is summarised away would leave a dangling tool
    # call in the preserved half.
    _rescued_tool_msg_indices: set[int] = set()
    for i, msg in enumerate(to_summarize):
        if isinstance(msg, ToolMessage) and str(msg.tool_call_id) in _rescued_ai_tool_call_ids:
            _rescued_tool_msg_indices.add(i)

    new_to_summarize: list[AnyMessage] = []
    rescued: list[AnyMessage] = []
    for i, msg in enumerate(to_summarize):
        if i in _orphan_ai_indices or i in _rescued_tool_msg_indices:
            rescued.append(msg)
        else:
            new_to_summarize.append(msg)

    # Insert rescued messages at the *start* of the preserved half in
    # their original order — each AIMessage precedes the ToolMessages it
    # owns, so every preserved ToolMessage stays paired correctly.
    return new_to_summarize, rescued + preserved


#: A partitioner takes the message list and a cutoff index
#: and returns ``(to_summarize, preserved)``.  The default
#: just slices; products that want skill rescue can pass a
#: richer implementation.
MessagePartitioner = Callable[[list[AnyMessage], int], tuple[list[AnyMessage], list[AnyMessage]]]


def skill_rescue_partitioner(
    skill_tool_names: Iterable[str],
    *,
    max_preserved_skills: int = 5,
) -> MessagePartitioner:
    """Build a partitioner that rescues recent skill-load tool calls.

    The base :func:`default_partitioner` summarises everything
    older than the cutoff, including the tool messages
    produced by ``read_skill`` (which can be tens of KB of
    SKILL.md content). The model then loses access to the
    skill's instructions for the rest of the conversation.

    This factory returns a partitioner that, after the
    base split, **moves recent skill-related tool messages
    from the to-summarise half into the preserved half**.
    Specifically: for every tool call whose name is in
    *skill_tool_names* and whose ``AIMessage`` / ``ToolMessage``
    pair is fully contained in the to-summarise half, move
    the entire pair to the preserved half. At most
    *max_preserved_skills* pairs are kept.

    When a rescued AIMessage also owns non-skill tool calls
    (e.g. ``bash`` alongside ``read_skill``), their ToolMessages
    are moved along too — otherwise they would be summarised
    away and leave a dangling tool call.

    Args:
        skill_tool_names: The set of tool names that count
            as "skill loads" (e.g. ``{"read_skill"}``).
        max_preserved_skills: Cap on how many recent skill
            pairs to rescue (the rest are still summarised).

    Returns:
        A :data:`MessagePartitioner` ready to be passed to
        :class:`SummarizationMiddleware` as
        ``message_partitioner=...``.
    """
    skill_set = frozenset(skill_tool_names)

    def _partitioner(
        messages: list[AnyMessage],
        cutoff_index: int,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        from langchain_core.messages import ToolMessage

        to_summarize, preserved = default_partitioner(messages, cutoff_index)

        # Build a tool_call_id → ToolMessage index map for the to-summarise half.
        # A skill "pair" is (AIMessage, ToolMessage) where the AIMessage's
        # tool_call[].id matches the ToolMessage's tool_call_id. The two
        # messages need not be adjacent (other messages can sit between them).
        tool_msg_by_id: dict[str, int] = {}
        for idx, msg in enumerate(to_summarize):
            if isinstance(msg, ToolMessage):
                tool_msg_by_id[str(msg.tool_call_id)] = idx

        # Walk the to-summarize half from the *end* (most recent first) and
        # collect the most recent skill-load AIMessages.  For each, record the
        # AIMessage index and *every* tool_call_id it owns: a single AIMessage
        # may invoke a skill tool alongside non-skill tools (e.g. bash), and
        # those ToolMessages must be rescued together with it — otherwise they
        # are summarised away and leave a dangling tool call.
        rescued_ai: list[tuple[int, set[str]]] = []
        for i in range(len(to_summarize) - 1, -1, -1):
            if len(rescued_ai) >= max_preserved_skills:
                break
            ai = to_summarize[i]
            if not isinstance(ai, AIMessage) or not getattr(ai, "tool_calls", None):
                continue
            # Inspect *every* tool_call on this AIMessage — not just the
            # first — so a skill call buried among non-skill calls is found.
            _tc_ids: set[str] = set()
            _has_skill = False
            for tc in ai.tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_id = str(tc.get("id") or "")
                if not tc_id or tc_id not in tool_msg_by_id:
                    continue
                _tc_ids.add(tc_id)
                if tc.get("name") in skill_set:
                    _has_skill = True
            if not _has_skill:
                continue
            rescued_ai.append((i, _tc_ids))

        if not rescued_ai:
            return to_summarize, preserved

        # Rescue every ToolMessage still in the to-summarise half that belongs
        # to a rescued AIMessage (both its skill results and non-skill results).
        _all_rescued_tc_ids: set[str] = set()
        for _, tc_ids in rescued_ai:
            _all_rescued_tc_ids.update(tc_ids)
        rescued_tool_indices: set[int] = set()
        for idx, msg in enumerate(to_summarize):
            if isinstance(msg, ToolMessage) and str(msg.tool_call_id) in _all_rescued_tc_ids:
                rescued_tool_indices.add(idx)

        _rescued_ai_indices = {idx for idx, _ in rescued_ai}
        new_to_summarize = [
            m for j, m in enumerate(to_summarize)
            if j not in _rescued_ai_indices and j not in rescued_tool_indices
        ]

        # Insert the rescued messages at the *start* of the preserved half,
        # most recent first, with each AIMessage immediately followed by the
        # ToolMessages it owns.  This contiguity is required by the tool-call
        # protocol: every `tool` role message must be preceded by the
        # `assistant` message carrying the matching `tool_calls` field.
        rescued: list[AnyMessage] = []
        for ai_idx, tc_ids in rescued_ai:  # already recent-first
            rescued.append(to_summarize[ai_idx])
            for j, m in enumerate(to_summarize):
                if j in rescued_tool_indices and isinstance(m, ToolMessage) and str(m.tool_call_id) in tc_ids:
                    rescued.append(m)
        return new_to_summarize, rescued + preserved

    return _partitioner


def _resolve_agent_name(runtime: Runtime | None) -> str | None:
    if runtime is not None and runtime.context is not None:
        name = runtime.context.get("agent_name")
        if name is not None:
            return name
    try:
        from langgraph.config import get_config

        cfg = get_config()
    except RuntimeError:
        return None
    return cfg.get("configurable", {}).get("agent_name")


def _count_tokens_approx(messages: Iterable[AnyMessage]) -> int:
    """Cheap token estimate: ~4 chars per token."""
    total = 0
    for m in messages:
        content = m.content
        if isinstance(content, str):
            total += max(1, len(content) // 4)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += max(1, len(str(block)) // 4)
                else:
                    total += max(1, len(str(block)) // 4)
    return total


def _render_messages(messages: Iterable[AnyMessage]) -> str:
    """Render a list of messages as a plain-text transcript for the LLM."""
    chunks: list[str] = []
    for m in messages:
        type_name = getattr(m, "type", m.__class__.__name__)
        content = m.content if isinstance(m.content, str) else str(m.content)
        chunks.append(f"[{type_name}] {content}")
    return "\n".join(chunks)


@dataclass
class SummarizationMiddlewareState(AgentState):
    """Compatible with the :class:`ThreadState` schema.

    No extra slots — the middleware only rewrites ``messages``.
    """


# ---------------------------------------------------------------------------
# Main middleware
# ---------------------------------------------------------------------------


class SummarizationMiddleware(AgentMiddleware[SummarizationMiddlewareState]):
    """Summarise older messages when a token budget is hit.

    Args:
        model: The chat model used to generate the summary
            (must be a ``BaseChatModel`` instance).
        max_tokens_before_summary: Trigger threshold; the
            middleware fires when the message-list token
            count exceeds this value.
        messages_to_keep: How many of the most recent
            messages to keep verbatim (default: 20).
        summary_prompt: ``str.format`` template; must
            accept ``{messages}``.
        hooks: Optional list of
            :class:`BeforeSummarizationHook` callbacks.
        message_partitioner: Optional custom partitioner
            (``default_partitioner`` by default — set this
            to enable skill rescue or other custom splits).
        skill_file_read_tool_names: Convenience for the
            DeerFlow preset; surfaces the default set of
            file-read tool names. Not used by the SDK
            middleware itself, kept for parity with the
            in-tree reference.
        preserve_recent_skill_count: Convenience for the
            DeerFlow preset; documents the contract for
            the in-tree partitioner. Not used by the SDK
            middleware itself.
        preserve_recent_skill_tokens: Same as above.
        preserve_recent_skill_tokens_per_skill: Same as above.
    """

    state_schema = SummarizationMiddlewareState

    def __init__(
        self,
        *,
        model: BaseChatModel,
        max_tokens_before_summary: int = 4000,
        messages_to_keep: int = 20,
        summary_prompt: str = DEFAULT_SUMMARY_PROMPT,
        hooks: Collection[BeforeSummarizationHook] | None = None,
        message_partitioner: MessagePartitioner | None = None,
        # The following are accepted for parity with the
        # in-tree reference but are not used by the SDK
        # middleware itself. Custom partitioners can read
        # them from the constructor.
        skill_file_read_tool_names: Collection[str] | None = None,
        preserve_recent_skill_count: int = 0,
        preserve_recent_skill_tokens: int = 0,
        preserve_recent_skill_tokens_per_skill: int = 0,
    ) -> None:
        super().__init__()
        self._model = model
        self._max_tokens = max(0, int(max_tokens_before_summary))
        self._messages_to_keep = max(0, int(messages_to_keep))
        self._summary_prompt = summary_prompt
        self._hooks: list[BeforeSummarizationHook] = list(hooks or [])
        self._partitioner = message_partitioner or default_partitioner

        # Stored for parity with the in-tree reference and for
        # use by callers' custom partitioners.
        self._skill_file_read_tool_names = frozenset(skill_file_read_tool_names or set())
        self._preserve_recent_skill_count = max(0, int(preserve_recent_skill_count))
        self._preserve_recent_skill_tokens = max(0, int(preserve_recent_skill_tokens))
        self._preserve_recent_skill_tokens_per_skill = max(0, int(preserve_recent_skill_tokens_per_skill))

    # ------------------------------------------------------------------
    # Trigger / cut-off
    # ------------------------------------------------------------------

    def _should_summarize(self, total_tokens: int) -> bool:
        if self._max_tokens <= 0:
            return False
        return total_tokens > self._max_tokens

    def _determine_cutoff_index(self, messages: list[AnyMessage]) -> int:
        """Index of the first message that survives the cut.

        Keeps at least ``messages_to_keep`` recent messages
        (cut at ``len(messages) - messages_to_keep``); never
        cuts past the start (returns 0 if too few messages).
        """
        if len(messages) <= self._messages_to_keep:
            return 0
        return max(0, len(messages) - self._messages_to_keep)

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------

    async def _asummarise(self, to_summarize: list[AnyMessage]) -> str:
        transcript = _render_messages(to_summarize)
        prompt = self._summary_prompt.format(messages=transcript)
        response = await self._model.ainvoke(prompt)
        content = response.content
        if isinstance(content, str):
            return content
        return _render_messages([AIMessage(content=str(content))])

    def _build_new_messages(self, summary: str) -> list[HumanMessage]:
        return [HumanMessage(content=f"Here is a summary of the conversation to date:\n\n{summary}", name="summary")]

    # ------------------------------------------------------------------
    # Skeletonisation
    # ------------------------------------------------------------------

    _SKELETON_CONTENT_THRESHOLD = 500  # chars — beyond this, replace with reference
    _SKELETON_TRUNCATE_LIMIT = 2000  # chars — max length for preserved tool results

    def _skeletonize_preserved(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """Convert preserved messages to lightweight skeletons.

        ToolMessages from ``read_skill`` with large content are replaced
        with short references.  Heavy ``write_file`` / ``bash`` tool-call
        arguments are stripped from AIMessages.  Short messages are kept
        as-is so the model retains the recent reasoning chain.

        Returns a new list (does not mutate the input).
        """
        result: list[AnyMessage] = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                result.append(self._skeletonize_tool_message(msg))
            elif isinstance(msg, AIMessage):
                result.append(self._skeletonize_ai_message(msg))
            else:
                result.append(msg)
        return result

    def _skeletonize_tool_message(self, msg: ToolMessage) -> ToolMessage:
        """Reduce a ToolMessage to a skeleton if its content is heavy."""
        name = getattr(msg, "name", "")
        content = msg.content if isinstance(msg.content, str) else str(msg.content)

        # read_skill / read_file results are reference material that the
        # summary already absorbed — replace with a lightweight pointer.
        if name in ("read_skill", "read_file") and len(content) > self._SKELETON_CONTENT_THRESHOLD:
            # Extract a short identifier — the file path is often in the
            # first line or the tool call args of the preceding AI.
            first_line = content.split("\n", 1)[0].strip()
            if first_line.startswith("# "):
                label = first_line[2:][:80]
            elif first_line.startswith("Directory listing for"):
                label = first_line[:120]
            else:
                label = first_line[:120]
            return ToolMessage(
                content=f"[Reference] {label} ({len(content)} chars — summary absorbed the content)",
                tool_call_id=msg.tool_call_id,
                name=name,
            )

        # Directory listings and other heavy results — truncate.
        if len(content) > self._SKELETON_TRUNCATE_LIMIT:
            return ToolMessage(
                content=content[: self._SKELETON_TRUNCATE_LIMIT]
                + f"\n...[truncated, {len(content)} chars total]",
                tool_call_id=msg.tool_call_id,
                name=name,
            )

        return msg

    def _skeletonize_ai_message(self, msg: AIMessage) -> AIMessage:
        """Strip heavy tool-call arguments from an AIMessage, keeping the reasoning text."""
        tc = getattr(msg, "tool_calls", None)
        if not tc:
            return msg

        skeleton_tc: list[dict] = []
        for t in tc:
            name = t.get("name", "?")
            args = t.get("args", {})
            skeleton: dict = {"name": name}

            if name == "write_file":
                # write_file args contain the full file content in
                # ``content`` / ``append_content`` — replace with a
                # size indicator.
                stripped: dict = {}
                for k, v in args.items():
                    if isinstance(v, str) and len(v) > 100:
                        stripped[k] = f"[{len(v)} chars]"
                    elif isinstance(v, str):
                        stripped[k] = v
                    else:
                        stripped[k] = v
                skeleton["args"] = stripped
            elif name == "bash":
                # bash commands can be long — truncate.
                cmd = args.get("command", "")
                skeleton["args"] = {
                    **args,
                    "command": cmd[:200] + "..." if len(str(cmd)) > 200 else cmd,
                }
            else:
                # Other tools — keep args as-is (usually short).
                skeleton["args"] = args

            tc_id = t.get("id")
            if tc_id:
                skeleton["id"] = tc_id
            skeleton_tc.append(skeleton)

        return AIMessage(
            content=msg.content,
            tool_calls=skeleton_tc,
            id=msg.id,
        )

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def _fire_hooks(
        self,
        to_summarize: list[AnyMessage],
        preserved: list[AnyMessage],
        runtime: Runtime,
    ) -> None:
        if not self._hooks:
            return
        event = SummarizationEvent(
            messages_to_summarize=tuple(to_summarize),
            preserved_messages=tuple(preserved),
            thread_id=resolve_thread_id(runtime),
            agent_name=_resolve_agent_name(runtime),
        )
        for hook in self._hooks:
            try:
                hook(event)
            except Exception:
                name = getattr(hook, "__name__", None) or type(hook).__name__
                logger.exception("BeforeSummarizationHook %s failed", name)

    # ------------------------------------------------------------------
    # before_model
    # ------------------------------------------------------------------

    def _maybe_summarise(self, state: SummarizationMiddlewareState, runtime: Runtime) -> dict | None:
        # The SDK middleware is async-only — the agent runtime
        # calls ``abefore_model`` when an event loop is available
        # and ``before_model`` (this method) only in synchronous
        # test contexts. The latter returns ``None`` so the
        # caller never accidentally summarises via a sync
        # ``model.invoke(...)`` path, which would block the
        # loop on chat models that wrap their async path.
        return None

    async def _amaybe_summarise(self, state: SummarizationMiddlewareState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None
        total_tokens = _count_tokens_approx(messages)
        if not self._should_summarize(total_tokens):
            return None

        cutoff = self._determine_cutoff_index(messages)
        if cutoff <= 0:
            return None

        logger.info(
            "Summarization triggered: total_tokens=%d, threshold=%d, message_count=%d, "
            "cutoff=%d, messages_to_keep=%d",
            total_tokens, self._max_tokens, len(messages), cutoff, self._messages_to_keep,
        )
        to_summarize, preserved = self._partitioner(messages, cutoff)
        logger.info(
            "Summarization split: to_summarize=%d messages, preserved=%d messages",
            len(to_summarize), len(preserved),
        )
        self._fire_hooks(to_summarize, preserved, runtime)
        summary = await self._asummarise(to_summarize)

        # Skeletonize preserved messages: replace heavy reference files
        # (read_skill returns 62k chars) with short pointers so the
        # model keeps the reasoning chain without the payload.
        skeleton = self._skeletonize_preserved(preserved)
        orig_chars = sum(len(str(m.content)) for m in preserved)
        skel_chars = sum(len(str(m.content)) for m in skeleton)
        logger.info(
            "Summarization complete: summary_length=%d chars, preserved=%d→%d messages, "
            "preserved_chars=%d→%d (%.0f%% reduction)",
            len(summary), len(preserved), len(skeleton),
            orig_chars, skel_chars, (1 - skel_chars / max(1, orig_chars)) * 100,
        )
        new_messages = self._build_new_messages(summary)
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages,
                *skeleton,
            ]
        }

    def before_model(self, state: SummarizationMiddlewareState, runtime: Runtime) -> dict | None:
        return self._maybe_summarise(state, runtime)

    async def abefore_model(self, state: SummarizationMiddlewareState, runtime: Runtime) -> dict | None:
        return await self._amaybe_summarise(state, runtime)
