"""Unit tests for :class:`agent_sdk.middlewares.SummarizationMiddleware`."""

from __future__ import annotations

from agent_sdk.middlewares.summarization import (
    BeforeSummarizationHook,
    SummarizationEvent,
    SummarizationMiddleware,
    default_partitioner,
)
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage


class _StubModel:
    """Stand-in for a chat model used by the middleware."""

    def __init__(self, content: str = "summary text") -> None:
        self._content = content
        self.invocations: list[str] = []

    def invoke(self, prompt: str):
        self.invocations.append(prompt)
        return AIMessage(content=self._content)

    async def ainvoke(self, prompt: str):
        self.invocations.append(prompt)
        return AIMessage(content=self._content)


class _FakeRuntime:
    """Minimal Runtime stand-in: ``context`` may be None for the
    thread_id / agent_name resolver, but the middleware should not
    crash on it.
    """

    def __init__(self, context=None) -> None:
        self.context = context


def _long_state(token_count: int = 200) -> dict:
    """Build a state with enough messages to exceed the default trigger."""
    # Each message contributes ~25 tokens (100 chars / 4). 8 messages
    # → ~200 tokens.
    msg = "x" * 100
    return {
        "messages": [
            HumanMessage(content=f"{i}:{msg}") if i % 2 == 0 else AIMessage(content=f"ai {i}:{msg}")
            for i in range(8)
        ]
    }


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


class TestTrigger:
    def test_under_threshold_noop(self) -> None:
        mw = SummarizationMiddleware(model=_StubModel(), max_tokens_before_summary=10_000)
        result = mw._maybe_summarise({"messages": [HumanMessage(content="hi")]}, runtime=None)  # type: ignore[arg-type]
        assert result is None

    def test_empty_state_noop(self) -> None:
        mw = SummarizationMiddleware(model=_StubModel(), max_tokens_before_summary=1)
        assert mw._maybe_summarise({"messages": []}, runtime=None) is None  # type: ignore[arg-type]

    def test_disabled_when_max_tokens_zero(self) -> None:
        mw = SummarizationMiddleware(model=_StubModel(), max_tokens_before_summary=0)
        result = mw._maybe_summarise(_long_state(token_count=200), runtime=None)  # type: ignore[arg-type]
        assert result is None

    def test_cutoff_isolates_recent_messages(self) -> None:
        # 8 messages + keep 3 → cutoff at index 5
        mw = SummarizationMiddleware(model=_StubModel(), max_tokens_before_summary=10, messages_to_keep=3)
        messages = [HumanMessage(content=f"m{i}") for i in range(8)]
        cutoff = mw._determine_cutoff_index(messages)
        assert cutoff == 8 - 3

    def test_cutoff_zero_when_too_few(self) -> None:
        mw = SummarizationMiddleware(model=_StubModel(), messages_to_keep=5)
        messages = [HumanMessage(content=f"m{i}") for i in range(3)]
        assert mw._determine_cutoff_index(messages) == 0


# ---------------------------------------------------------------------------
# before_model
# ---------------------------------------------------------------------------


class TestBeforeModel:
    def test_sync_path_is_no_op(self) -> None:
        # The SDK middleware is async-only. The sync
        # ``_maybe_summarise`` returns ``None`` so the agent
        # runtime never accidentally drives summarisation via
        # a blocking ``model.invoke(...)`` call (which would
        # dead-lock on chat models that wrap their async path).
        model = _StubModel(content="this is the summary")
        mw = SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=10,  # tiny threshold so any state fires
            messages_to_keep=2,
        )
        result = mw._maybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is None

    async def test_async_path_returns_replace_messages_update(self) -> None:
        model = _StubModel(content="this is the summary")
        mw = SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=10,
            messages_to_keep=2,
        )
        result = await mw._amaybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is not None
        msgs = result["messages"]
        # First item is a RemoveMessage that signals "drop everything".
        assert isinstance(msgs[0], RemoveMessage)
        # Then a HumanMessage carrying the summary.
        summary_msg = msgs[1]
        assert isinstance(summary_msg, HumanMessage)
        assert "summary" in summary_msg.content
        assert summary_msg.name == "summary"
        # Then the preserved tail.
        assert len(msgs) == 1 + 1 + 2  # remove + summary + 2 kept

    async def test_async_path_uses_ainvoke(self) -> None:
        model = _StubModel(content="async summary")
        mw = SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=10,
            messages_to_keep=2,
        )
        result = await mw._amaybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is not None
        assert model.invocations  # ainvoke was called

    def test_sync_path_uses_invoke(self) -> None:
        # The SDK middleware is async-only. The sync path
        # (``_maybe_summarise``) intentionally does NOT
        # invoke the model — it returns ``None`` so a sync
        # test context cannot accidentally block the event
        # loop on a chat model that wraps its async path.
        model = _StubModel()
        mw = SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=10,
            messages_to_keep=2,
        )
        result = mw._maybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is None
        assert not model.invocations


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def _capture_hook():
    captured: list[SummarizationEvent] = []

    def hook(event: SummarizationEvent) -> None:
        captured.append(event)

    return hook, captured


class TestHooks:
    async def test_hook_fires_before_summarisation(self) -> None:
        hook, captured = _capture_hook()
        mw = SummarizationMiddleware(
            model=_StubModel(),
            max_tokens_before_summary=10,
            messages_to_keep=2,
            hooks=[hook],
        )
        result = await mw._amaybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is not None
        assert len(captured) == 1
        event = captured[0]
        # The event carries the partition we are about to summarise / preserve.
        assert len(event.messages_to_summarize) > 0
        assert len(event.preserved_messages) > 0
        # No runtime context → thread_id and agent_name are None.
        assert event.thread_id is None
        assert event.agent_name is None

    async def test_hook_exception_is_swallowed(self) -> None:
        def bad_hook(event):
            raise RuntimeError("boom")

        mw = SummarizationMiddleware(
            model=_StubModel(),
            max_tokens_before_summary=10,
            messages_to_keep=2,
            hooks=[bad_hook],
        )
        # The middleware must not crash on a bad hook.
        result = await mw._amaybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert result is not None

    def test_protocol_membership(self) -> None:
        # The Protocol is runtime_checkable, so a bare callable
        # works as a hook.
        assert isinstance(lambda e: None, BeforeSummarizationHook)


# ---------------------------------------------------------------------------
# Custom partitioner
# ---------------------------------------------------------------------------


class TestCustomPartitioner:
    async def test_custom_partitioner_called(self) -> None:
        calls: list = []

        def custom(messages, cutoff):
            calls.append((len(messages), cutoff))
            return default_partitioner(messages, cutoff)

        mw = SummarizationMiddleware(
            model=_StubModel(),
            max_tokens_before_summary=10,
            messages_to_keep=2,
            message_partitioner=custom,
        )
        await mw._amaybe_summarise(_long_state(), runtime=None)  # type: ignore[arg-type]
        assert calls == [(8, 6)]


# ---------------------------------------------------------------------------
# default_partitioner tool-call pairing
# ---------------------------------------------------------------------------


class TestDefaultPartitioner:
    def test_moves_all_tool_messages_of_multi_call_aimessage(self) -> None:
        """Regression: a rescued AIMessage with [bash, read_skill] must move
        *both* ToolMessages to preserved, not just the preserved one.

        The older logic rescued only the AIMessage (because it owned a
        preserved ToolMessage) and left the other tool call's ToolMessage
        in the to-summarise half — summarising it away left a dangling tool
        call that the next model call rejected.
        """
        from langchain_core.messages import ToolMessage

        # cutoff_index = 3 → summarise [0..2], preserve [3..].
        # AIMessage(b1, r1) at index 1; ToolMessage(b1) at index 2 is in the
        # to-summarise half, ToolMessage(r1) at index 3 is in the preserved half.
        state = [
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "b1", "name": "bash", "args": {"command": "ls"}},
                    {"id": "r1", "name": "read_skill", "args": {"name": "x"}},
                ],
            ),
            ToolMessage(content="bash out", tool_call_id="b1"),
            ToolMessage(content="<skill body>", tool_call_id="r1"),
            HumanMessage(content="late q"),
        ]
        to_summarize, preserved = default_partitioner(state, 3)

        # The AIMessage and BOTH ToolMessages leave the to-summarise half.
        assert not any(isinstance(m, AIMessage) and m.tool_calls for m in to_summarize)
        assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "b1" for m in to_summarize)
        assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "r1" for m in to_summarize)
        assert [m for m in to_summarize if not isinstance(m, ToolMessage)] == [state[0]]

        # preserved = [AIMessage, ToolMessage(b1), ToolMessage(r1), late q]
        # with each ToolMessage preceded by its owning AIMessage.
        assert isinstance(preserved[0], AIMessage)
        assert {tc["id"] for tc in preserved[0].tool_calls} == {"b1", "r1"}
        assert isinstance(preserved[1], ToolMessage) and preserved[1].tool_call_id == "b1"
        assert isinstance(preserved[2], ToolMessage) and preserved[2].tool_call_id == "r1"
        assert preserved[3].content == "late q"


# ---------------------------------------------------------------------------
# Built-in skill_rescue_partitioner (5.5)
# ---------------------------------------------------------------------------


class TestSkillRescuePartitioner:
    def test_rescues_recent_skill_tool_call(self) -> None:
        from agent_sdk.middlewares.summarization import skill_rescue_partitioner
        from langchain_core.messages import ToolMessage

        partitioner = skill_rescue_partitioner({"read_skill"})

        # Build a state with a skill load near the *end* of the to-summarise half.
        # cutoff_index = 6 means indices 0..5 summarise, 6..7 preserved.
        # We want a read_skill pair inside the to-summarise half.
        state = [
            HumanMessage(content="q1"),
            HumanMessage(content="q2"),
            HumanMessage(content="q3"),
            HumanMessage(content="q4"),
            AIMessage(
                content="",
                tool_calls=[{"id": "skill-1", "name": "read_skill", "args": {"name": "x"}}],
            ),
            ToolMessage(content="long skill body", tool_call_id="skill-1"),
            HumanMessage(content="late q"),
            HumanMessage(content="very late q"),
        ]
        # Cutoff at 6 → summarise [0..5], preserve [6..7].
        to_summarize, preserved = partitioner(state, 6)
        # The skill AIMessage + ToolMessage moved out of to_summarize.
        assert all(not (isinstance(m, AIMessage) and m.tool_calls and m.tool_calls[0]["id"] == "skill-1") for m in to_summarize)
        assert all(not (isinstance(m, ToolMessage) and m.tool_call_id == "skill-1") for m in to_summarize)
        # The skill pair is at the *front* of the preserved half.
        # **CRITICAL order**: AIMessage must come before its
        # ToolMessage — the OpenAI tool-call protocol requires every
        # `tool` role message to be preceded by an `assistant` message
        # with the matching `tool_calls` field.
        assert isinstance(preserved[0], AIMessage)
        assert preserved[0].tool_calls[0]["id"] == "skill-1"
        assert isinstance(preserved[1], ToolMessage)
        assert preserved[1].tool_call_id == "skill-1"
        # Then the original preserved messages follow.
        assert preserved[2].content == "late q"
        assert preserved[3].content == "very late q"

    def test_no_rescue_when_no_skill_calls(self) -> None:
        from agent_sdk.middlewares.summarization import skill_rescue_partitioner

        partitioner = skill_rescue_partitioner({"read_skill"})
        state = [HumanMessage(content=f"q{i}") for i in range(6)]
        to_summarize, preserved = partitioner(state, 4)
        # Identical to default_partitioner when no skill calls are present.
        assert to_summarize == state[:4]
        assert preserved == state[4:]

    def test_caps_rescued_pairs(self) -> None:
        from agent_sdk.middlewares.summarization import skill_rescue_partitioner
        from langchain_core.messages import ToolMessage

        # max_preserved_skills=2; we put 3 skill calls in the to-summarise half.
        partitioner = skill_rescue_partitioner({"read_skill"}, max_preserved_skills=2)
        state = []
        for i in range(3):
            state.append(HumanMessage(content=f"q{i}"))
            state.append(AIMessage(content="", tool_calls=[{"id": f"s{i}", "name": "read_skill", "args": {}}]))
            state.append(ToolMessage(content="body", tool_call_id=f"s{i}"))
        state.append(HumanMessage(content="late"))
        # Cutoff at 9 → summarise [0..8] (3 humans + 3 AIMsg + 3 ToolMsg),
        # preserve [9] (1 message).
        to_summarize, preserved = partitioner(state, 9)
        # Only the most recent 2 skill pairs are rescued; the oldest one is
        # still in to_summarize.
        assert any(isinstance(m, ToolMessage) and m.tool_call_id == "s0" for m in to_summarize)
        # 2 rescued AIMessages first (recent-first), then their 2 ToolMessages.
        ai_indices = [i for i, m in enumerate(preserved) if isinstance(m, AIMessage)]
        tm_indices = [i for i, m in enumerate(preserved) if isinstance(m, ToolMessage)]
        assert len(ai_indices) == 2
        assert len(tm_indices) == 2
        # AIMessage (s1 or s2) at preserved[0] — recent pair first.
        assert preserved[0].tool_calls[0]["id"] in {"s1", "s2"}
        # 4 rescued + 1 original = 5 preserved.
        assert len(preserved) == 5

    def test_rescues_skill_when_first_tool_call_is_not_skill(self) -> None:
        """Regression: AIMessage with [bash, read_skill] must still rescue."""
        from agent_sdk.middlewares.summarization import skill_rescue_partitioner
        from langchain_core.messages import ToolMessage

        partitioner = skill_rescue_partitioner({"read_skill"})
        # AIMessage whose first tool call is bash (non-skill) and second
        # is read_skill. The older behaviour inspected only tool_calls[0]
        # and would skip this message entirely.
        state = [
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "b1", "name": "bash", "args": {"command": "ls"}},
                    {"id": "r1", "name": "read_skill", "args": {"name": "x"}},
                ],
            ),
            ToolMessage(content="bash out", tool_call_id="b1"),
            ToolMessage(content="<skill body>", tool_call_id="r1"),
            HumanMessage(content="late q"),
        ]
        # Cutoff at 4 → summarise [0..3], preserve [4]. The AIMessage
        # is in the to-summarise half and must be rescued because it
        # contains a read_skill tool call.
        to_summarize, preserved = partitioner(state, 4)
        # The AIMessage AND both ToolMessages leave the to-summarise half —
        # the bash result must be rescued alongside read_skill, otherwise it
        # would be summarised away and leave a dangling tool call.
        assert not any(isinstance(m, AIMessage) and m.tool_calls for m in to_summarize)
        assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "b1" for m in to_summarize)
        assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "r1" for m in to_summarize)
        # Rescued AIMessage at the front, immediately followed by its
        # ToolMessages in tool_call order (b1 then r1).
        assert isinstance(preserved[0], AIMessage)
        assert [tc["id"] for tc in preserved[0].tool_calls] == ["b1", "r1"]
        assert isinstance(preserved[1], ToolMessage)
        assert preserved[1].tool_call_id == "b1"
        assert isinstance(preserved[2], ToolMessage)
        assert preserved[2].tool_call_id == "r1"
        assert preserved[3].content == "late q"

    def test_skill_rescue_style_partitioner(self) -> None:
        """A custom partitioner that *rescues* specific tool calls."""

        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        state = {
            "messages": [
                HumanMessage(content="q1"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "read_file", "args": {"path": "/mnt/skills/x.md"}},
                    ],
                ),
                ToolMessage(content="<skill x.md content>", tool_call_id="c1", name="read_file"),
                HumanMessage(content="q2"),
                AIMessage(content="answer"),
            ]
        }

        def skill_rescue(messages, cutoff):
            to_summarise, preserved = default_partitioner(messages, cutoff)
            # Keep the skill load (any AIMessage whose tool call
            # references the skills root, plus the matching tool
            # response) in the preserved set.
            rescued = preserved + [
                m
                for m in to_summarise
                if isinstance(m, AIMessage)
                and any("/mnt/skills/" in (tc.get("args", {}) or {}).get("path", "") for tc in (m.tool_calls or []))
            ]
            return to_summarise, rescued

        mw = SummarizationMiddleware(
            model=_StubModel(),
            max_tokens_before_summary=0,  # we test partitioner directly
            messages_to_keep=0,
            message_partitioner=skill_rescue,
        )
        # Bypass the trigger by calling the partitioner manually.
        to_summarise, preserved = mw._partitioner(state["messages"], len(state["messages"]) - 2)
        # The first two messages go to "summarise".
        assert len(to_summarise) == 3
        # The skill-rescue partitioner appends the AIMessage with the skills tool call to preserved.
        assert any(isinstance(m, AIMessage) and m.tool_calls and m.tool_calls[0]["id"] == "c1" for m in preserved)
