"""Unit tests for :class:`agent_sdk.middlewares.ViewImageMiddleware`."""

from __future__ import annotations

from agent_sdk.middlewares.view_image import VIEW_IMAGE_TOOL_NAME, ViewImageMiddleware
from agent_sdk.runtime.thread_state import ViewedImageData
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _ai_with_view_image(call_id: str = "call-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": VIEW_IMAGE_TOOL_NAME, "args": {"path": "/a.png"}}],
    )


def _tool_response(call_id: str = "call-1", content: str = "ok") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=VIEW_IMAGE_TOOL_NAME)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestDetection:
    def test_no_messages_no_inject(self) -> None:
        mw = ViewImageMiddleware()
        result = mw._inject({"messages": []})
        assert result is None

    def test_no_ai_message_no_inject(self) -> None:
        mw = ViewImageMiddleware()
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._inject(state) is None

    def test_ai_without_view_image_no_inject(self) -> None:
        mw = ViewImageMiddleware()
        ai = AIMessage(content="", tool_calls=[{"id": "c", "name": "bash", "args": {}}])
        state = {"messages": [ai]}
        assert mw._inject(state) is None

    def test_view_image_not_yet_completed_no_inject(self) -> None:
        mw = ViewImageMiddleware()
        ai = _ai_with_view_image()
        state = {"messages": [ai]}  # no ToolMessage
        assert mw._inject(state) is None


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


class TestInjection:
    def test_inject_after_completion(self) -> None:
        mw = ViewImageMiddleware()
        ai = _ai_with_view_image()
        tool = _tool_response()
        viewed: dict[str, ViewedImageData] = {
            "/a.png": {"base64": "AAAA", "mime_type": "image/png"},
        }
        state = {"messages": [ai, tool], "viewed_images": viewed}
        result = mw._inject(state)
        assert result is not None
        # The new HumanMessage is appended.
        new_msgs = result["messages"]
        assert len(new_msgs) == 1
        assert isinstance(new_msgs[0], HumanMessage)
        # viewed_images is cleared so the next turn does not re-inject.
        assert result["viewed_images"] == {}

    def test_injected_message_contains_image_data(self) -> None:
        mw = ViewImageMiddleware()
        ai = _ai_with_view_image()
        tool = _tool_response()
        viewed: dict[str, ViewedImageData] = {
            "/x.png": {"base64": "BBBB", "mime_type": "image/jpeg"},
        }
        state = {"messages": [ai, tool], "viewed_images": viewed}
        result = mw._inject(state)
        assert result is not None
        content = result["messages"][0].content
        # Multimodal content: a header text block + a per-image
        # text block + an image_url block.
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        # The header block carries the marker.
        assert "Here are the images" in content[0]["text"]
        # The per-image text block carries the path + mime type.
        text_blocks = [b for b in content if b.get("type") == "text"]
        assert any("/x.png" in b["text"] for b in text_blocks)
        # The image data must be in a data: URL.
        image_blocks = [b for b in content if b.get("type") == "image_url"]
        assert any("data:image/jpeg;base64,BBBB" in b["image_url"]["url"] for b in image_blocks)

    def test_does_not_inject_twice(self) -> None:
        mw = ViewImageMiddleware()
        ai = _ai_with_view_image()
        tool = _tool_response()
        # A previous human message after the AI carries the marker.
        already = HumanMessage(content="Here are the images you've viewed: ...")
        state = {
            "messages": [ai, tool, already],
            "viewed_images": {"/a.png": {"base64": "X", "mime_type": "image/png"}},
        }
        # No new injection because the marker is already present.
        assert mw._inject(state) is None

    def test_no_viewed_images_still_injects_fallback_message(self) -> None:
        mw = ViewImageMiddleware()
        ai = _ai_with_view_image()
        tool = _tool_response()
        state = {"messages": [ai, tool], "viewed_images": {}}
        result = mw._inject(state)
        # Even with no images we still inject a "no images viewed" notice.
        assert result is not None
        # Content is a list of blocks; the notice is the only text block.
        content = result["messages"][0].content
        assert isinstance(content, list)
        text_blocks = [b for b in content if b.get("type") == "text"]
        assert any("No images have been viewed" in b["text"] for b in text_blocks)

    def test_custom_tool_name(self) -> None:
        mw = ViewImageMiddleware(tool_name="look_at")
        ai = AIMessage(
            content="",
            tool_calls=[{"id": "c", "name": "look_at", "args": {"path": "/y.png"}}],
        )
        tool = ToolMessage(content="ok", tool_call_id="c", name="look_at")
        state = {
            "messages": [ai, tool],
            "viewed_images": {"/y.png": {"base64": "Z", "mime_type": "image/png"}},
        }
        result = mw._inject(state)
        assert result is not None
