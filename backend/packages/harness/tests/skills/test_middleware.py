"""Unit tests for :class:`agent_sdk.skills.middleware.SkillsMiddleware`."""

from __future__ import annotations

from pathlib import Path

from agent_sdk.skills.middleware import SkillsMiddleware
from langchain_core.messages import HumanMessage, SystemMessage


def _write_skill(skill_dir: Path, name: str, description: str = "d") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8"
    )


class TestSkillsMiddleware:
    def test_no_prompt_when_no_skills(self, tmp_path: Path) -> None:
        mw = SkillsMiddleware(skills_path=tmp_path)
        result = mw.before_model({"messages": [HumanMessage(content="hi")]}, runtime=None)  # type: ignore[arg-type]
        assert result is None

    def test_injects_available_skills_block(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "public" / "alpha", "alpha", "an alpha skill")
        _write_skill(tmp_path / "public" / "beta", "beta", "a beta skill")
        mw = SkillsMiddleware(skills_path=tmp_path)
        result = mw.before_model(
            {"messages": [SystemMessage(content="system"), HumanMessage(content="hi")]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert result is not None
        sys_msg = result["messages"][0]
        assert isinstance(sys_msg, SystemMessage)
        assert "<available_skills>" in sys_msg.content
        assert "alpha" in sys_msg.content
        assert "beta" in sys_msg.content
        # Original system content preserved.
        assert "system" in sys_msg.content

    def test_idempotent_when_block_already_present(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "public" / "alpha", "alpha", "an alpha skill")
        mw = SkillsMiddleware(skills_path=tmp_path)
        # Pre-injected by a previous turn.
        first = mw.before_model(
            {"messages": [SystemMessage(content="system")]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert first is not None
        msgs_with_block = first["messages"]
        # Second call should be a no-op.
        result = mw.before_model(
            {"messages": list(msgs_with_block)},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert result is None

    def test_allowed_names_whitelist(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "public" / "alpha", "alpha", "alpha desc")
        _write_skill(tmp_path / "public" / "beta", "beta", "beta desc")
        mw = SkillsMiddleware(skills_path=tmp_path, allowed_names=["alpha"])
        result = mw.before_model(
            {"messages": [HumanMessage(content="hi")]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert result is not None
        sys_msg = result["messages"][0]
        assert "alpha" in sys_msg.content
        assert "beta" not in sys_msg.content

    def test_prepends_system_message_when_none(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "public" / "alpha", "alpha", "an alpha skill")
        mw = SkillsMiddleware(skills_path=tmp_path)
        result = mw.before_model(
            {"messages": [HumanMessage(content="hi")]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert result is not None
        msgs = result["messages"]
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert msgs[1].content == "hi"

    def test_invalidate_cache(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "public" / "alpha", "alpha", "v1")
        mw = SkillsMiddleware(skills_path=tmp_path)
        # Warm the cache by re-using a system message that already
        # contains the block (idempotent path).
        block = mw._get_prompt()
        pre_injected = SystemMessage(content=f"x\n\n{block}")
        first = mw.before_model(
            {"messages": [pre_injected]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        # Block is already present → middleware is a no-op.
        assert first is None

        # Mutate the on-disk skill (rename).
        (tmp_path / "public" / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha2\ndescription: v1\n---\n", encoding="utf-8"
        )
        # Without invalidation, the cached prompt is reused → alpha is still in it.
        # The middleware injects because the new SystemMessage has no block.
        second_sys = SystemMessage(content="fresh turn — no block")
        cached = mw.before_model(
            {"messages": [second_sys]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert cached is not None
        # Cached prompt still references "alpha" (not "alpha2").
        assert "alpha " in cached["messages"][0].content
        assert "alpha2" not in cached["messages"][0].content

        # With invalidation, the new content is read.
        mw.invalidate_cache()
        third_sys = SystemMessage(content="another fresh turn")
        fresh = mw.before_model(
            {"messages": [third_sys]},  # type: ignore[arg-type]
            runtime=None,  # type: ignore[arg-type]
        )
        assert fresh is not None
        assert "alpha2" in fresh["messages"][0].content
