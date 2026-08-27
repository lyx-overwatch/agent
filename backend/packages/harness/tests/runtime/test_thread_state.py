"""Unit tests for :class:`agent_sdk.runtime.thread_state.ThreadState` and
its reducers (``merge_artifacts`` / ``merge_viewed_images``).
"""

from __future__ import annotations

from agent_sdk.runtime.thread_state import (
    SandboxState,
    ThreadDataState,
    ThreadState,
    ViewedImageData,
    merge_artifacts,
    merge_viewed_images,
)


class TestMergeArtifacts:
    def test_both_none_returns_empty(self) -> None:
        assert merge_artifacts(None, None) == []

    def test_existing_none(self) -> None:
        assert merge_artifacts(None, ["a", "b"]) == ["a", "b"]

    def test_new_none(self) -> None:
        assert merge_artifacts(["a", "b"], None) == ["a", "b"]

    def test_concatenates(self) -> None:
        assert merge_artifacts(["a"], ["b", "c"]) == ["a", "b", "c"]

    def test_dedup_preserves_order(self) -> None:
        # First appearance wins.
        result = merge_artifacts(["a", "b"], ["b", "c", "a"])
        assert result == ["a", "b", "c"]

    def test_empty_lists(self) -> None:
        assert merge_artifacts([], []) == []
        assert merge_artifacts(["a"], []) == ["a"]
        assert merge_artifacts([], ["a"]) == ["a"]


class TestMergeViewedImages:
    def test_both_none_returns_empty(self) -> None:
        assert merge_viewed_images(None, None) == {}

    def test_existing_none(self) -> None:
        images = {"p": ViewedImageData(base64="abc", mime_type="image/png")}
        assert merge_viewed_images(None, images) == images

    def test_new_none(self) -> None:
        images = {"p": ViewedImageData(base64="abc", mime_type="image/png")}
        assert merge_viewed_images(images, None) == images

    def test_empty_new_dict_clears(self) -> None:
        # The vision middleware uses the empty-dict signal to
        # mean "I just rendered the images; drop them."
        existing = {"p": ViewedImageData(base64="abc", mime_type="image/png")}
        assert merge_viewed_images(existing, {}) == {}

    def test_merges_with_new_winning(self) -> None:
        existing = {
            "a": ViewedImageData(base64="aaa", mime_type="image/png"),
            "b": ViewedImageData(base64="bbb", mime_type="image/png"),
        }
        new = {
            "b": ViewedImageData(base64="BBB-NEW", mime_type="image/jpeg"),
            "c": ViewedImageData(base64="ccc", mime_type="image/png"),
        }
        merged = merge_viewed_images(existing, new)
        # TypedDicts are plain dicts at runtime; access by key.
        assert merged["a"]["base64"] == "aaa"
        assert merged["b"]["base64"] == "BBB-NEW"
        assert merged["c"]["base64"] == "ccc"


class TestThreadState:
    def test_inherits_agent_state(self) -> None:
        # The base :class:`AgentState` provides ``messages``.
        assert "messages" in ThreadState.__annotations__

    def test_artifacts_is_annotated(self) -> None:
        # ``artifacts`` is an annotated slot (uses the reducer).
        assert "artifacts" in ThreadState.__annotations__

    def test_viewed_images_is_annotated(self) -> None:
        assert "viewed_images" in ThreadState.__annotations__

    def test_sandbox_is_not_required(self) -> None:
        # The ``sandbox`` slot is ``NotRequired`` so empty state
        # is valid (no sandbox yet).
        assert "sandbox" in ThreadState.__annotations__

    def test_thread_data_is_not_required(self) -> None:
        assert "thread_data" in ThreadState.__annotations__


class TestStateShapeSubtypes:
    def test_sandbox_state_shape(self) -> None:
        # The TypedDict fields are accessible (not behaviourally
        # tested — typed dicts are erased at runtime).
        assert "sandbox_id" in SandboxState.__annotations__

    def test_thread_data_state_shape(self) -> None:
        for field in ("workspace_path", "uploads_path", "outputs_path"):
            assert field in ThreadDataState.__annotations__

    def test_viewed_image_data_shape(self) -> None:
        for field in ("base64", "mime_type"):
            assert field in ViewedImageData.__annotations__
