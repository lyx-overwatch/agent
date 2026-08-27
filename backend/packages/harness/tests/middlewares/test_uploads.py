"""Unit tests for :class:`agent_sdk.middlewares.UploadsMiddleware`."""

from __future__ import annotations

from agent_sdk.middlewares.uploads import (
    DEFAULT_VIRTUAL_PREFIX,
    UploadsMiddleware,
)
from agent_sdk.paths.provider import PathProvider
from langchain_core.messages import HumanMessage


class _TmpPathProvider(PathProvider):
    """PathProvider rooted at a caller-supplied tmp dir."""

    def __init__(self, base) -> None:
        from pathlib import Path

        self._base = Path(base)

    def get_base_dir(self):
        return self._base

    def _for(self, thread_id: str, kind: str):
        return self._base / "users" / "default" / "threads" / thread_id / kind

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for(thread_id, "workspace")

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for(thread_id, "uploads")

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for(thread_id, "outputs")

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for(thread_id, "user-data")

    def get_skills_dir(self):
        return self._base / "skills"

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None):
        return None

    def get_virtual_prefix(self) -> str:
        return DEFAULT_VIRTUAL_PREFIX

    def is_host_bash_allowed(self) -> bool:
        return True


class _FakeRuntime:
    def __init__(self, context=None) -> None:
        self.context = context or {}


def _msg_with_files(files) -> HumanMessage:
    return HumanMessage(content="hi", additional_kwargs={"files": files})


# ---------------------------------------------------------------------------
# before_agent
# ---------------------------------------------------------------------------


class TestBeforeAgent:
    def test_no_files_returns_none(self, tmp_path) -> None:
        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        state = {"messages": [HumanMessage(content="hi")]}
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t"}))
        assert result is None

    def test_no_messages_returns_none(self, tmp_path) -> None:
        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        result = mw.before_agent({"messages": []}, runtime=_FakeRuntime({"thread_id": "t"}))
        assert result is None

    def test_last_message_not_human_returns_none(self, tmp_path) -> None:
        from langchain_core.messages import AIMessage

        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        state = {"messages": [AIMessage(content="hi")]}
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t"}))
        assert result is None

    def test_injects_block_for_new_files(self, tmp_path) -> None:
        # Create the uploads dir + a real file
        uploads = tmp_path / "users" / "default" / "threads" / "t1" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "doc.txt").write_text("hello", encoding="utf-8")

        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        state = {
            "messages": [
                _msg_with_files(
                    [
                        {"filename": "doc.txt", "size": 5, "path": "/mnt/user-data/uploads/doc.txt"},
                    ]
                )
            ]
        }
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t1"}))
        assert result is not None
        # uploaded_files slot is set
        assert len(result["uploaded_files"]) == 1
        # The HumanMessage has been replaced with one that has the
        # <uploaded_files> block prepended.
        new_msg = result["messages"][-1]
        assert "<uploaded_files>" in new_msg.content
        assert "doc.txt" in new_msg.content

    def test_historical_files_listed(self, tmp_path) -> None:
        uploads = tmp_path / "users" / "default" / "threads" / "t2" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "old.txt").write_text("old", encoding="utf-8")
        # New file (also in additional_kwargs) does NOT appear
        # in the historical list (excluded by name).
        (uploads / "new.txt").write_text("new", encoding="utf-8")

        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        state = {
            "messages": [
                _msg_with_files(
                    [
                        {"filename": "new.txt", "size": 3, "path": "/mnt/user-data/uploads/new.txt"},
                    ]
                )
            ]
        }
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t2"}))
        assert result is not None
        content = result["messages"][-1].content
        # Historical block lists old.txt
        assert "old.txt" in content
        # new.txt listed as the new upload
        assert "new.txt" in content
        # Section markers
        assert "previous messages" in content

    def test_filename_with_path_is_rejected(self, tmp_path) -> None:
        # Defensive: reject ``..`` style names that could escape the dir.
        uploads = tmp_path / "users" / "default" / "threads" / "t3" / "uploads"
        uploads.mkdir(parents=True)
        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        state = {
            "messages": [
                _msg_with_files(
                    [
                        {"filename": "../etc/passwd", "size": 0, "path": "/mnt/etc/passwd"},
                    ]
                )
            ]
        }
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t3"}))
        # No valid file → no injection.
        assert result is None

    def test_virtual_prefix_in_message(self, tmp_path) -> None:
        uploads = tmp_path / "users" / "default" / "threads" / "t4" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "f.txt").write_text("x", encoding="utf-8")
        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider, virtual_prefix="/custom/root")
        state = {
            "messages": [
                _msg_with_files(
                    [
                        {"filename": "f.txt", "size": 1, "path": "/custom/root/uploads/f.txt"},
                    ]
                )
            ]
        }
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t4"}))
        assert "/custom/root/uploads/" in result["messages"][-1].content

    def test_preserves_multimodal_content(self, tmp_path) -> None:
        uploads = tmp_path / "users" / "default" / "threads" / "t5" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        provider = _TmpPathProvider(tmp_path)
        mw = UploadsMiddleware(path_provider=provider)
        msg = _msg_with_files([{"filename": "img.png", "size": 8, "path": "/mnt/user-data/uploads/img.png"}])
        msg.content = [
            {"type": "text", "text": "describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]
        state = {"messages": [msg]}
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t5"}))
        new_content = result["messages"][-1].content
        # The prepended block is the first text block; the original
        # blocks (text + image_url) are preserved after it.
        assert isinstance(new_content, list)
        assert new_content[0]["type"] == "text"
        assert "<uploaded_files>" in new_content[0]["text"]
        # The original text block is the second one.
        assert new_content[1]["type"] == "text"
        assert new_content[1]["text"] == "describe this image"
        # The original image block is the third one.
        assert new_content[2]["type"] == "image_url"
