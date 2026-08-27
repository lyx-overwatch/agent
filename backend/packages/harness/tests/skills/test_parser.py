"""Unit tests for :func:`agent_sdk.skills.parser.parse_skill_file`."""

from __future__ import annotations

from pathlib import Path


def _write(skill_dir: Path, name: str, *, description: str = "d", license: str | None = None) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    f = skill_dir / "SKILL.md"
    front_matter_lines = [f"name: {name}", f"description: {description}"]
    if license is not None:
        front_matter_lines.append(f"license: {license}")
    body = "\n".join(front_matter_lines)
    f.write_text(f"---\n{body}\n---\n\n# {name}\n", encoding="utf-8")
    return f


class TestParseSkillFile:
    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        assert parse_skill_file(tmp_path / "SKILL.md") is None

    def test_returns_none_for_wrong_filename(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        (tmp_path / "README.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
        assert parse_skill_file(tmp_path / "README.md") is None

    def test_returns_none_without_front_matter(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        f = _write(tmp_path, "x")
        f.write_text("# no front matter\n", encoding="utf-8")
        assert parse_skill_file(f) is None

    def test_returns_none_for_missing_name(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        f = tmp_path / "SKILL.md"
        f.write_text("---\ndescription: d\n---\n", encoding="utf-8")
        assert parse_skill_file(f) is None

    def test_returns_none_for_missing_description(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: x\n---\n", encoding="utf-8")
        assert parse_skill_file(f) is None

    def test_returns_none_for_invalid_yaml(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: x\ndescription: [unclosed\n---\n", encoding="utf-8")
        assert parse_skill_file(f) is None

    def test_returns_skill_for_valid_file(self, tmp_path: Path) -> None:
        from agent_sdk.skills.parser import parse_skill_file

        f = _write(tmp_path, "bootstrap", description="Bootstrap", license="MIT")
        skill = parse_skill_file(f, relative_path=Path("public/bootstrap"))
        assert skill is not None
        assert skill.name == "bootstrap"
        assert skill.description == "Bootstrap"
        assert skill.license == "MIT"
        assert skill.relative_path == Path("public/bootstrap")
        assert skill.enabled is True  # default until loader applies a filter
