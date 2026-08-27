"""ViewImageMiddleware — inject image details into the LLM context.

This module is a re-implementation (per ADR-010) of
``deerflow.agents.middlewares.view_image_middleware``.

The middleware:

1. Runs before each LLM call.
2. Looks for the most recent ``AIMessage`` that contains
   ``view_image`` tool calls.
3. Checks that **all** of those tool calls have been
   completed (have a corresponding ``ToolMessage``).
4. If so, creates a ``HumanMessage`` with the images'
   base64 / mime-type data and appends it to the message
   list, so the LLM can see and analyse the images.

To avoid re-injecting the same images on every turn, the
middleware also clears the ``viewed_images`` reducer slot
(by writing an empty dict).  The reducer interprets
``{}`` as "you can drop the map now" (see
:func:`agent_sdk.runtime.thread_state.merge_viewed_images`).

The middleware is idempotent: it refuses to inject the
same image message twice in a row (it scans the messages
after the last assistant turn for the marker string).
"""

from __future__ import annotations

import logging
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


#: Tool name this middleware watches for. Must match the
#: ``view_image`` tool factory in
#: :mod:`agent_sdk.tools.factory`.
VIEW_IMAGE_TOOL_NAME: str = "view_image"

#: Marker string the middleware looks for in already-injected
#: image messages to avoid double-injection.
_IMAGE_MARKER: str = "Here are the images you've viewed"


class ViewImageMiddlewareState:
    """Marker class — the real state is :class:`ThreadState`.

    The middleware relies only on the slots already provided
    by :class:`agent_sdk.runtime.ThreadState` (``messages``
    and the ``viewed_images`` reducer), so no extra fields
    are required. This stub exists so the AgentMiddleware
    generic is satisfied.
    """


class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    """Inject image details as a ``HumanMessage`` before each LLM call.

    Optional constructor:
        tool_name: Override the tool name to watch for
            (default: :data:`VIEW_IMAGE_TOOL_NAME`).
    """

    def __init__(self, tool_name: str = VIEW_IMAGE_TOOL_NAME) -> None:
        super().__init__()
        self._tool_name = tool_name

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _has_view_image_tool(self, message: AIMessage) -> bool:
        tool_calls = getattr(message, "tool_calls", None) or []
        return any(tc.get("name") == self._tool_name for tc in tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        tool_calls = getattr(assistant_msg, "tool_calls", None) or []
        if not tool_calls:
            return False
        tool_call_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
        if not tool_call_ids:
            return False
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False
        completed_ids = {
            msg.tool_call_id
            for msg in messages[assistant_idx + 1 :]
            if isinstance(msg, ToolMessage) and msg.tool_call_id
        }
        return tool_call_ids.issubset(completed_ids)

    def _already_injected(self, messages: list, assistant_msg: AIMessage) -> bool:
        """Return ``True`` if a previous image-details message is already present."""
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                content_str = str(msg.content)
                if _IMAGE_MARKER in content_str:
                    return True
        return False

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _create_image_details_message(self, viewed_images: dict) -> list:
        """Build the multimodal content blocks for the image-details HumanMessage."""
        if not viewed_images:
            return [{"type": "text", "text": "No images have been viewed."}]

        blocks: list = [{"type": "text", "text": _IMAGE_MARKER + ":"}]
        for image_path, image_data in viewed_images.items():
            mime_type = image_data.get("mime_type", "unknown")
            base64_data = image_data.get("base64", "")
            blocks.append({"type": "text", "text": f"\n- **{image_path}** ({mime_type})"})
            if base64_data:
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
                    }
                )
        return blocks

    # ------------------------------------------------------------------
    # before_model
    # ------------------------------------------------------------------

    def _inject(self, state) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_ai = self._get_last_assistant_message(messages)
        if last_ai is None:
            return None
        if not self._has_view_image_tool(last_ai):
            return None
        if not self._all_tools_completed(messages, last_ai):
            return None
        if self._already_injected(messages, last_ai):
            return None

        viewed_images = state.get("viewed_images") or {}
        content = self._create_image_details_message(viewed_images)
        human_msg = HumanMessage(content=content)

        logger.debug("Injecting image details message with %d image(s)", len(viewed_images))

        # Append the new human message and clear the viewed_images
        # reducer so subsequent turns do not re-inject the same
        # images.
        return {
            "messages": [human_msg],
            "viewed_images": {},
        }

    @override
    def before_model(self, state, runtime: Runtime) -> dict | None:
        return self._inject(state)

    @override
    async def abefore_model(self, state, runtime: Runtime) -> dict | None:
        return self._inject(state)
