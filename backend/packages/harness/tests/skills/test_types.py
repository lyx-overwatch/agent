"""Unit tests for :class:`agent_sdk.skills.types.Skill`."""

from __future__ import annotations

from pathlib import Path


class TestSkillPath:
    def test_skill_path_empty_at_root(self, tmp_path: Path) -> None:
        from agent_sdk.skills.types import Skill

        # A skill whose directory *is* the root → relative_path is '.'
        s = Skill(
            name="bootstrap",
            description="Init",
            license=None,
            skill_dir=tmp_path,
            skill_file=tmp_path / "SKILL.md",
            relative_path=Path("."),
        )
        assert s.skill_path == ""

    def test_skill_path_with_nested_dir(self, tmp_path: Path) -> None:
        from agent_sdk.skills.types import Skill

        s = Skill(
            name="code-review",
            description="Review",
            license=None,
            skill_dir=tmp_path / "code-review",
            skill_file=tmp_path / "code-review" / "SKILL.md",
            relative_path=Path("code-review"),
        )
        assert s.skill_path == "code-review"

    def test_repr_is_compact(self, tmp_path: Path) -> None:
        from agent_sdk.skills.types import Skill

        s = Skill(
            name="x",
            description="long description that should not appear in repr",
            license=None,
            skill_dir=tmp_path,
            skill_file=tmp_path / "SKILL.md",
            relative_path=Path("x"),
        )
        r = repr(s)
        assert "Skill(name=" in r
        assert "long description" not in r
