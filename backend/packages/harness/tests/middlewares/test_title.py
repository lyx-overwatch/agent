"""Unit tests for :class:`agent_sdk.middlewares.TitleMiddleware`."""

from __future__ import annotations

from agent_sdk.middlewares.title import TitleMiddleware, TitlePrompts
from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

_FAKE_MODEL = FakeListChatModel(responses=["hi"])


def _state(human: str = "hello world", ai: str = "hi there") -> dict:
    return {
        "messages": [
            HumanMessage(content=human),
            AIMessage(content=ai),
        ]
    }


def _req(state: dict) -> ModelRequest:
    return ModelRequest(model=_FAKE_MODEL, messages=state.get("messages", []), state=state)


def _run(mw: TitleMiddleware, state: dict):
    """Run one sync ``wrap_model_call`` round-trip over *state*."""
    req = _req(state)
    return mw.wrap_model_call(req, lambda r: ModelResponse(result=r.state["messages"]))


async def _arun(mw: TitleMiddleware, state: dict):
    """Run one async ``awrap_model_call`` round-trip over *state*."""
    req = _req(state)

    async def handler(r: ModelRequest) -> ModelResponse:
        return ModelResponse(result=r.state["messages"])

    return await mw.awrap_model_call(req, handler)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class TestShouldGenerate:
    def test_no_messages(self) -> None:
        mw = TitleMiddleware()
        assert mw._should_generate_title(_req({"messages": []}), ModelResponse(result=[])) is False

    def test_single_message(self) -> None:
        mw = TitleMiddleware()
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_generate_title(_req(state), ModelResponse(result=[])) is False

    def test_full_exchange(self) -> None:
        mw = TitleMiddleware()
        state = _state()
        assert mw._should_generate_title(_req(state), ModelResponse(result=state["messages"])) is True

    def test_already_has_title(self) -> None:
        mw = TitleMiddleware()
        state = _state()
        state["title"] = "Existing"
        assert mw._should_generate_title(_req(state), ModelResponse(result=state["messages"])) is False

    def test_multiple_user_messages(self) -> None:
        mw = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="hi"),
                AIMessage(content="hello"),
                HumanMessage(content="another question"),
                AIMessage(content="another answer"),
            ]
        }
        # Second user message means the first turn has already produced a title.
        assert mw._should_generate_title(_req(state), ModelResponse(result=state["messages"])) is False


# ---------------------------------------------------------------------------
# Sync fallback
# ---------------------------------------------------------------------------


class TestSyncFallback:
    def test_fallback_title(self) -> None:
        mw = TitleMiddleware()
        result = _run(mw, _state(human="a long question about stuff"))
        assert isinstance(result, ExtendedModelResponse)
        title = result.command.update["title"]
        # Default fallback caps at 50 chars.
        assert len(title) <= 50
        assert "a long question" in title

    def test_fallback_title_short(self) -> None:
        mw = TitleMiddleware()
        result = _run(mw, _state(human="hi"))
        assert isinstance(result, ExtendedModelResponse)
        assert result.command.update["title"] == "hi"

    def test_fallback_title_empty(self) -> None:
        mw = TitleMiddleware()
        result = _run(mw, _state(human="", ai=""))
        assert isinstance(result, ExtendedModelResponse)
        assert result.command.update["title"] == "New Conversation"

    def test_no_decision_no_update(self) -> None:
        mw = TitleMiddleware()
        result = _run(mw, {"messages": []})
        # No first exchange → the response is returned unchanged (no title command).
        assert not isinstance(result, ExtendedModelResponse)


# ---------------------------------------------------------------------------
# Async path
# ---------------------------------------------------------------------------


class _FakeModel:
    """Minimal chat model that returns a fixed string from ``ainvoke``."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.invocations = 0

    async def ainvoke(self, prompt):
        self.invocations += 1
        # Return a simple namespace so the middleware can read .content
        return type("R", (), {"content": self._content})()


class TestAsyncPath:
    async def test_async_generates_title(self) -> None:
        model = _FakeModel(content="A great conversation")
        mw = TitleMiddleware(model_factory=lambda: model)
        result = await _arun(mw, _state())
        assert isinstance(result, ExtendedModelResponse)
        assert result.command.update["title"] == "A great conversation"
        assert model.invocations == 1

    async def test_async_truncates_long_title(self) -> None:
        model = _FakeModel(content="x" * 200)
        mw = TitleMiddleware(model_factory=lambda: model)
        result = await _arun(mw, _state())
        assert len(result.command.update["title"]) == 80  # default max_chars

    async def test_async_strips_think_tags(self) -> None:
        model = _FakeModel(content=" thinking\nhidden reasoning\n response\nReal title")
        mw = TitleMiddleware(model_factory=lambda: model)
        result = await _arun(mw, _state())
        assert isinstance(result, ExtendedModelResponse)
        assert "thinking" not in result.command.update["title"]
        assert "Real title" in result.command.update["title"]

    async def test_async_strips_quotes(self) -> None:
        model = _FakeModel(content='"Quoted title"')
        mw = TitleMiddleware(model_factory=lambda: model)
        result = await _arun(mw, _state())
        assert result.command.update["title"] == "Quoted title"

    async def test_async_falls_back_on_model_error(self) -> None:
        class _BrokenModel:
            async def ainvoke(self, prompt):
                raise RuntimeError("boom")

        mw = TitleMiddleware(model_factory=lambda: _BrokenModel())
        result = await _arun(mw, _state(human="user question"))
        assert isinstance(result, ExtendedModelResponse)
        # Falls back to the user-message prefix.
        assert "user question" in result.command.update["title"]

    async def test_async_no_model_factory_falls_back(self) -> None:
        mw = TitleMiddleware(model_factory=None)
        result = await _arun(mw, _state(human="user question"))
        assert isinstance(result, ExtendedModelResponse)
        assert "user question" in result.command.update["title"]


# ---------------------------------------------------------------------------
# TitlePrompts
# ---------------------------------------------------------------------------


class TestTitlePrompts:
    def test_default(self) -> None:
        p = TitlePrompts.default()
        assert p.max_words == 8
        assert p.max_chars == 80
        # The template must accept the documented kwargs.
        rendered = p.prompt_template.format(max_words=8, user_msg="x", assistant_msg="y")
        assert "{messages}" not in rendered
