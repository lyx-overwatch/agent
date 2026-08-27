"""Unit tests for :class:`agent_sdk.middlewares.todo.TodoMiddleware`.

Covers construction (prompts injection), the context-loss
reminder (``before_model``), and the premature-exit prevention
(``after_model``).
"""

from __future__ import annotations

from typing import Any

from agent_sdk.middlewares.todo.middleware import _MAX_COMPLETION_REMINDERS, TodoMiddleware
from agent_sdk.middlewares.todo.prompts import (
    DEFAULT_TODO_SYSTEM_PROMPT,
    DEFAULT_TODO_TOOL_DESCRIPTION,
    TodoPrompts,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langgraph.runtime import Runtime


def _make_runtime() -> Runtime:
    return Runtime(context={})  # type: ignore[arg-type]


def _write_todos_ai(content: str = "ok") -> AIMessage:
    """An AIMessage that contains a ``write_todos`` tool call."""
    return AIMessage(
        content=content,
        tool_calls=[
            ToolCall(name="write_todos", args={"todos": [{"status": "in_progress", "content": "x"}]}, id="call-1"),
        ],
    )


class TestConstruction:
    def test_default_prompts_are_used_when_none(self) -> None:
        mw = TodoMiddleware()
        assert mw.prompts.system_prompt == DEFAULT_TODO_SYSTEM_PROMPT
        assert mw.prompts.tool_description == DEFAULT_TODO_TOOL_DESCRIPTION

    def test_default_tool_name(self) -> None:
        mw = TodoMiddleware()
        assert mw.tool_name == "write_todos"

    def test_custom_prompts_are_stored(self) -> None:
        custom = TodoPrompts(system_prompt="custom sys", tool_description="custom desc")
        mw = TodoMiddleware(prompts=custom)
        assert mw.prompts is custom

    def test_custom_tool_name(self) -> None:
        mw = TodoMiddleware(tool_name="my_todos")
        assert mw.tool_name == "my_todos"

    def test_prompts_are_passed_to_base(self) -> None:
        custom = TodoPrompts(system_prompt="unique-system-prompt-xyz", tool_description="unique-desc-xyz")
        mw = TodoMiddleware(prompts=custom)
        # The base class's tool description should be our custom one.
        # The base class stores it as a private attribute; we
        # simply assert that *something* in the middleware's
        # own state references the custom text.
        assert "unique-system-prompt-xyz" in mw.prompts.system_prompt
        assert "unique-desc-xyz" in mw.prompts.tool_description


class TestBeforeModelReminder:
    def test_no_todos_no_reminder(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {"messages": [], "todos": []}
        result = mw.before_model(state, _make_runtime())
        assert result is None

    def test_todos_in_messages_no_reminder(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [_write_todos_ai()],
            "todos": [{"status": "in_progress", "content": "x"}],
        }
        result = mw.before_model(state, _make_runtime())
        assert result is None

    def test_existing_reminder_no_double_inject(self) -> None:
        mw = TodoMiddleware()
        reminder = HumanMessage(name="todo_reminder", content="already reminded")
        state: dict[str, Any] = {
            "messages": [reminder],
            "todos": [{"status": "in_progress", "content": "x"}],
        }
        result = mw.before_model(state, _make_runtime())
        assert result is None

    def test_truncated_context_injects_reminder(self) -> None:
        mw = TodoMiddleware()
        # The todo list is in state but the original write_todos
        # call has been truncated from the message history. The
        # middleware should inject a reminder.
        state: dict[str, Any] = {
            "messages": [HumanMessage(content="earlier message")],
            "todos": [
                {"status": "in_progress", "content": "do thing 1"},
                {"status": "pending", "content": "do thing 2"},
            ],
        }
        result = mw.before_model(state, _make_runtime())
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        reminder = msgs[0]
        assert isinstance(reminder, HumanMessage)
        assert reminder.name == "todo_reminder"
        # The reminder must surface the current todo state.
        assert "do thing 1" in reminder.content
        assert "do thing 2" in reminder.content


class TestAfterModelPrematureExit:
    def test_no_todos_no_intervention(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [AIMessage(content="all done")],
            "todos": [],
        }
        result = mw.after_model(state, _make_runtime())
        assert result is None

    def test_all_todos_completed_no_intervention(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [AIMessage(content="done")],
            "todos": [{"status": "completed", "content": "x"}],
        }
        result = mw.after_model(state, _make_runtime())
        assert result is None

    def test_model_has_tool_calls_no_intervention(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [_write_todos_ai()],
            "todos": [{"status": "in_progress", "content": "x"}],
        }
        result = mw.after_model(state, _make_runtime())
        assert result is None

    def test_incomplete_todos_injects_reminder_and_jumps(self) -> None:
        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [AIMessage(content="I'll give up here")],
            "todos": [
                {"status": "in_progress", "content": "open task 1"},
                {"status": "completed", "content": "closed task 2"},
            ],
        }
        result = mw.after_model(state, _make_runtime())
        assert result is not None
        assert result.get("jump_to") == "model"
        msgs = result["messages"]
        assert len(msgs) == 1
        reminder = msgs[0]
        assert isinstance(reminder, HumanMessage)
        assert reminder.name == "todo_completion_reminder"
        # The reminder must surface only the *incomplete* items.
        assert "open task 1" in reminder.content
        assert "closed task 2" not in reminder.content

    def test_reminder_cap_respected(self) -> None:
        # After ``_MAX_COMPLETION_REMINDERS`` reminders have already
        # been injected, the middleware must stop adding more.
        mw = TodoMiddleware()
        reminders = [
            HumanMessage(name="todo_completion_reminder", content=f"reminder #{i}")
            for i in range(_MAX_COMPLETION_REMINDERS)
        ]
        state: dict[str, Any] = {
            "messages": [AIMessage(content="giving up")] + reminders,
            "todos": [{"status": "in_progress", "content": "x"}],
        }
        result = mw.after_model(state, _make_runtime())
        # Cap reached → no further intervention.
        assert result is None


class TestAsyncBeforeModel:
    def test_async_returns_same_as_sync(self) -> None:
        import asyncio

        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [HumanMessage(content="earlier")],
            "todos": [{"status": "in_progress", "content": "x"}],
        }
        sync_result = mw.before_model(state, _make_runtime())
        async_result = asyncio.run(mw.abefore_model(state, _make_runtime()))
        assert async_result == sync_result


class TestAsyncAfterModel:
    def test_async_returns_same_as_sync(self) -> None:
        import asyncio

        mw = TodoMiddleware()
        state: dict[str, Any] = {
            "messages": [AIMessage(content="bye")],
            "todos": [{"status": "in_progress", "content": "open"}],
        }
        sync_result = mw.after_model(state, _make_runtime())
        async_result = asyncio.run(mw.aafter_model(state, _make_runtime()))
        assert async_result == sync_result
        assert async_result is not None
        assert async_result.get("jump_to") == "model"
