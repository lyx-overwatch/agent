"""TitleMiddleware — automatic thread-title generation.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.title_middleware``.

The middleware generates a short title for the thread after
the first user/assistant exchange. It does so by calling a
caller-supplied model factory with a small prompt; the
synchronous ``wrap_model_call`` path uses a local fallback
(simple user-message prefix) so it never blocks the agent
loop on an LLM call. The async path tries the LLM first
and falls back on any failure.

Brand-neutrality:
    The middleware does **not** know about DeerFlow's title
    config. The caller wires it up by passing:

    * a ``model_factory`` callable that returns a
      ``BaseChatModel``;
    * a ``prompts`` object that supplies the prompt template
      and limits (see :class:`TitlePrompts`).

    The default :class:`TitlePrompts` is brand-neutral; the
    DeerFlow preset provides its own.

Uses :meth:`wrap_model_call` so it composes into the single
``model`` graph node instead of creating a separate
``after_model`` node — saving 1 recursion_limit step per
iteration.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NotRequired, Protocol, override, runtime_checkable

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TitlePrompts:
    """Prompt template and length limits for title generation.

    Attributes:
        prompt_template: ``str.format`` template.  Must
            accept ``max_words``, ``user_msg``,
            ``assistant_msg`` keyword arguments.
        max_words: Soft target word count — passed to the
            model in the prompt.
        max_chars: Hard cap on the stored title.  The parser
            truncates the model output to this length.
        fallback_max_chars: Cap used by the local
            ``_fallback_title`` heuristic (always ``<= max_chars``).
    """

    prompt_template: str = (
        "Generate a short title (max {max_words} words) for a conversation. "
        "Output ONLY the title — no quotes, no preamble.\n\n"
        "User: {user_msg}\n\n"
        "Assistant: {assistant_msg}"
    )
    max_words: int = 8
    max_chars: int = 80
    fallback_max_chars: int = 50

    @classmethod
    def default(cls) -> TitlePrompts:
        """Return the brand-neutral default :class:`TitlePrompts`."""
        return cls()


@runtime_checkable
class TitleModelFactory(Protocol):
    """Callable that returns a chat model for title generation.

    The factory may be sync (``BaseChatModel``) or async
    (an awaitable that resolves to a ``BaseChatModel``).
    The middleware's async path awaits the result.
    """

    def __call__(self) -> Any: ...


# Convenience type alias for the user-facing model factory.
TitleModelFactoryFn = Callable[[], Any]


class TitleMiddlewareState(AgentState):
    """Compatible with the :class:`ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Auto-generate a short title for the thread after the first exchange.

    Args:
        model_factory: Optional callable that returns a
            ``BaseChatModel``.  Required for the async path;
            the sync path always uses a local fallback.
        prompts: Optional :class:`TitlePrompts`.  When
            ``None``, the brand-neutral default is used.
    """

    state_schema = TitleMiddlewareState

    def __init__(
        self,
        model_factory: TitleModelFactoryFn | None = None,
        prompts: TitlePrompts | None = None,
    ) -> None:
        super().__init__()
        self._model_factory = model_factory
        self._prompts = prompts or TitlePrompts.default()

    # ------------------------------------------------------------------
    # Content extraction
    # ------------------------------------------------------------------

    def _normalize_content(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p for p in (self._normalize_content(item) for item in content) if p)
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str):
                return text
            nested = content.get("content")
            if nested is not None:
                return self._normalize_content(nested)
        return ""

    def _strip_think_tags(self, text: str) -> str:
        return re.sub(r" thinking[\s\S]*? response", "", text, flags=re.IGNORECASE).strip()

    # Regex to strip <uploaded_files>...</uploaded_files> blocks (complete and truncated)
    _UPLOADED_FILES_RE = re.compile(r"<uploaded_files>[\s\S]*?(?:</uploaded_files>|$)", re.IGNORECASE)

    def _extract_user_msg(self, state: dict) -> str:
        """Extract the first user message content from state.

        The ``<uploaded_files>`` XML block (if any) is stripped so the
        fallback title is based on the actual user message text.
        """
        messages = state.get("messages", [])
        for m in messages:
            if getattr(m, "type", None) == "human":
                raw = self._normalize_content(m.content)
                return self._UPLOADED_FILES_RE.sub("", raw).strip()
        return ""

    def _extract_first_ai_content(self, response: ModelResponse) -> str:
        """Extract the first AI message content from the model response."""
        result = getattr(response, "result", None)
        if not result:
            return ""
        for msg in result:
            if isinstance(msg, AIMessage):
                return self._strip_think_tags(self._normalize_content(msg.content))
        return ""

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------

    def _should_generate_title(self, request: ModelRequest, response: ModelResponse) -> bool:
        """Check whether this is the first exchange and a title is needed."""
        state = request.state
        if state.get("title"):
            return False
        messages = state.get("messages", [])
        user_count = sum(1 for m in messages if getattr(m, "type", None) == "human")
        if user_count != 1:
            return False
        # Ensure the model has actually produced a response.
        result = getattr(response, "result", None)
        if not result:
            return False
        return any(isinstance(msg, AIMessage) for msg in result)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_title(self, content: object) -> str:
        text = self._strip_think_tags(self._normalize_content(content))
        text = text.strip().strip('"').strip("'")
        if len(text) > self._prompts.max_chars:
            return text[: self._prompts.max_chars]
        return text

    def _fallback_title(self, user_msg: str) -> str:
        cap = min(self._prompts.max_chars, self._prompts.fallback_max_chars)
        if len(user_msg) > cap:
            return user_msg[:cap].rstrip() + "..."
        return user_msg if user_msg else "New Conversation"

    # ------------------------------------------------------------------
    # wrap_model_call hooks
    # ------------------------------------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse | ExtendedModelResponse:
        response = handler(request)
        return self._apply(request, response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse | ExtendedModelResponse:
        response = await handler(request)
        return await self._aapply(request, response)

    def _apply(self, request: ModelRequest, response: ModelResponse) -> ModelResponse | ExtendedModelResponse:
        if not self._should_generate_title(request, response):
            return response
        user_msg = self._extract_user_msg(request.state)
        title = self._fallback_title(user_msg)
        return ExtendedModelResponse(
            model_response=response,
            command=Command(update={"title": title}),
        )

    async def _aapply(self, request: ModelRequest, response: ModelResponse) -> ModelResponse | ExtendedModelResponse:
        if not self._should_generate_title(request, response):
            return response
        user_msg = self._extract_user_msg(request.state)
        if self._model_factory is not None:
            try:
                model = self._model_factory()
                assistant_msg = self._extract_first_ai_content(response)
                prompt = self._prompts.prompt_template.format(
                    max_words=self._prompts.max_words,
                    user_msg=user_msg[:500],
                    assistant_msg=assistant_msg[:500],
                )
                llm_response = await model.ainvoke(prompt)
                title = self._parse_title(llm_response.content)
                if title:
                    return ExtendedModelResponse(
                        model_response=response,
                        command=Command(update={"title": title}),
                    )
            except Exception:
                logger.debug("Async title generation failed; falling back to local title", exc_info=True)
        title = self._fallback_title(user_msg)
        return ExtendedModelResponse(
            model_response=response,
            command=Command(update={"title": title}),
        )