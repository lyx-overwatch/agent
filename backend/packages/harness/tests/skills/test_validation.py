"""Unit tests for :mod:`agent_sdk.skills.validation`."""

from __future__ import annotations

from pathlib import Path


def _write_skill_md(
    skill_dir: Path,
    name: str = "my-skill",
    description: str = "A test skill",
    *,
    extra: str | None = None,
) -> Path:
    """Create a minimal SKILL.md with valid frontmatter."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    f = skill_dir / "SKILL.md"
    front_lines = [f"name: {name}", f"description: {description}"]
    if extra:
        front_lines.append(extra)
    body = "\n".join(front_lines)
    f.write_text(f"---\n{body}\n---\n\n# {name}\n", encoding="utf-8")
    return f


class TestValidateSkillFrontmatter:
    def test_valid_frontmatter(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="code-review", description="Review code")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is True
        assert name == "code-review"
        assert "valid" in msg.lower()

    def test_missing_skill_md(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "SKILL.md not found" in msg
        assert name is None

    def test_no_yaml_frontmatter(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("# No frontmatter\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "No YAML frontmatter" in msg

    def test_invalid_frontmatter_format(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: x\n", encoding="utf-8")  # No closing ---
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "format" in msg.lower()

    def test_missing_name(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\ndescription: d\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "Missing 'name'" in msg

    def test_missing_description(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: x\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "Missing 'description'" in msg

    def test_name_not_a_string(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: 42\ndescription: d\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "must be a string" in msg

    def test_name_empty(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: '  '\ndescription: d\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "Name cannot be empty" in msg

    def test_name_with_underscores_rejected(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="my_skill")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "hyphen-case" in msg

    def test_name_starting_with_hyphen(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="-bad")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "start/end with hyphen" in msg

    def test_name_ending_with_hyphen(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="bad-")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "start/end with hyphen" in msg

    def test_name_with_consecutive_hyphens(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="bad--name")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "consecutive hyphens" in msg

    def test_name_too_long(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, name="a" * 65)
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "too long" in msg

    def test_description_too_long(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, description="x" * 1025)
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "too long" in msg

    def test_description_with_angle_brackets(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(tmp_path, description="<script>alert(1)</script>")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "angle brackets" in msg

    def test_description_not_a_string(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\nname: x\ndescription: 123\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "must be a string" in msg

    def test_unexpected_frontmatter_keys(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text(
            "---\nname: x\ndescription: d\nbogus: true\n---\n", encoding="utf-8"
        )
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "Unexpected key" in msg

    def test_allowed_keys_accepted(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        _write_skill_md(
            tmp_path,
            name="my-skill",
            description="A skill",
            extra="license: MIT\nversion: '1.0'\nauthor: test",
        )
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is True
        assert name == "my-skill"

    def test_invalid_yaml_raises_gracefully(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text(
            "---\nname: x\ndescription: [unclosed\n---\n", encoding="utf-8"
        )
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "Invalid YAML" in msg

    def test_frontmatter_not_a_dict(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        f = tmp_path / "SKILL.md"
        f.write_text("---\n- item1\n- item2\n---\n", encoding="utf-8")
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is False
        assert "YAML dictionary" in msg

    def test_valid_name_at_boundary(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        name = "a" * 64  # Exactly 64 chars
        _write_skill_md(tmp_path, name=name)
        ok, msg, parsed = validate_skill_frontmatter(tmp_path)
        assert ok is True
        assert parsed == name

    def test_valid_description_at_boundary(self, tmp_path: Path) -> None:
        from agent_sdk.skills.validation import validate_skill_frontmatter

        desc = "x" * 1024  # Exactly 1024 chars
        _write_skill_md(tmp_path, description=desc)
        ok, msg, name = validate_skill_frontmatter(tmp_path)
        assert ok is True
        assert name == "my-skill"
