"""Unit tests for :class:`agent_sdk.middlewares.ThreadDataMiddleware`."""

from __future__ import annotations

import pytest
from agent_sdk.middlewares.thread_data import ThreadDataMiddleware
from agent_sdk.paths.provider import PathProvider
from langchain_core.messages import HumanMessage


class _FixedPathProvider(PathProvider):
    """Deterministic provider that returns fixed paths per thread."""

    def __init__(self, base: str = "/tmp/agent_sdk_test") -> None:
        self._base = base

    def get_base_dir(self):
        from pathlib import Path

        return Path(self._base)

    def _for_thread(self, thread_id: str, kind: str):
        from pathlib import Path

        return Path(self._base) / thread_id / kind

    def get_workspace_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for_thread(thread_id, "workspace")

    def get_uploads_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for_thread(thread_id, "uploads")

    def get_outputs_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for_thread(thread_id, "outputs")

    def get_user_data_dir(self, thread_id: str, *, user_id: str | None = None):
        return self._for_thread(thread_id, "user-data")

    def get_skills_dir(self):
        from pathlib import Path

        return Path(self._base) / "skills"

    def get_default_venv_dir(self, thread_id: str, *, user_id: str | None = None):
        return None

    def get_virtual_prefix(self) -> str:
        return "/mnt/user-data"

    def is_host_bash_allowed(self) -> bool:
        return True


class _FakeRuntime:
    """Minimal stand-in for a langgraph Runtime with .context."""

    def __init__(self, context=None) -> None:
        self.context = context or {}


def _state_with_message(content: str = "hi") -> dict:
    return {"messages": [HumanMessage(content=content)]}


class TestThreadDataMiddleware:
    def test_lazy_init_does_not_create_dirs(self, tmp_path) -> None:
        provider = _FixedPathProvider(base=str(tmp_path))
        mw = ThreadDataMiddleware(path_provider=provider, lazy_init=True)
        state = _state_with_message()
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t-1"}))
        assert result is not None
        assert set(result["thread_data"].keys()) == {"workspace_path", "uploads_path", "outputs_path"}
        # The directories must NOT have been created.

        assert not (tmp_path / "t-1" / "workspace").exists()

    def test_eager_init_creates_dirs(self, tmp_path) -> None:
        provider = _FixedPathProvider(base=str(tmp_path))
        mw = ThreadDataMiddleware(path_provider=provider, lazy_init=False)
        state = _state_with_message()
        result = mw.before_agent(state, runtime=_FakeRuntime({"thread_id": "t-2"}))
        assert result is not None
        # All three directories must have been created.
        assert (tmp_path / "t-2" / "workspace").is_dir()
        assert (tmp_path / "t-2" / "uploads").is_dir()
        assert (tmp_path / "t-2" / "outputs").is_dir()

    def test_missing_thread_id_raises(self) -> None:
        provider = _FixedPathProvider()
        mw = ThreadDataMiddleware(path_provider=provider)
        with pytest.raises(ValueError, match="Thread ID is required"):
            mw.before_agent(_state_with_message(), runtime=_FakeRuntime({}))

    def test_message_stamped_with_run_id_and_timestamp(self) -> None:
        provider = _FixedPathProvider()
        mw = ThreadDataMiddleware(path_provider=provider, lazy_init=True)
        result = mw.before_agent(
            _state_with_message("hello"),
            runtime=_FakeRuntime({"thread_id": "t-3", "run_id": "r-1"}),
        )
        last_msg = result["messages"][-1]
        assert isinstance(last_msg, HumanMessage)
        assert last_msg.additional_kwargs["run_id"] == "r-1"
        assert "timestamp" in last_msg.additional_kwargs

    def test_no_message_no_change(self) -> None:
        provider = _FixedPathProvider()
        mw = ThreadDataMiddleware(path_provider=provider)
        result = mw.before_agent({"messages": []}, runtime=_FakeRuntime({"thread_id": "t-4"}))
        # No HumanMessage to stamp; thread_data is still set.
        assert result is not None
        # The path should contain the thread id (separator-agnostic
        # so the test passes on both POSIX and Windows).
        assert "t-4" in result["thread_data"]["workspace_path"]
        assert result["thread_data"]["workspace_path"].endswith(("t-4/workspace", "t-4\\workspace"))
        # messages list is left empty.
        assert result["messages"] == []
