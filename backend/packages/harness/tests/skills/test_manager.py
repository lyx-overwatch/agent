"""Unit tests for :mod:`agent_sdk.skills.manager` path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestValidateSkillName:
    @pytest.mark.parametrize("name", ["bootstrap", "code-review", "x", "a-1-b"])
    def test_valid(self, name: str) -> None:
        from agent_sdk.skills.manager import validate_skill_name

        assert validate_skill_name(name) == name

    @pytest.mark.parametrize("name", ["", "Code", "code_review", "code review", "CODE"])
    def test_invalid(self, name: str) -> None:
        from agent_sdk.skills.manager import validate_skill_name

        with pytest.raises(ValueError, match="hyphen-case"):
            validate_skill_name(name)

    def test_too_long(self) -> None:
        from agent_sdk.skills.manager import validate_skill_name

        with pytest.raises(ValueError, match="64 characters"):
            validate_skill_name("a" * 65)


class TestCustomSkillPaths:
    def test_get_custom_skill_dir_creates_root(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import get_custom_skill_dir, get_custom_skills_dir

        d = get_custom_skill_dir("alpha", tmp_path)
        # The 'custom' root is created eagerly; the per-skill dir is not.
        assert get_custom_skills_dir(tmp_path).exists()
        assert d.parent.exists()
        assert d.name == "alpha"

    def test_get_custom_skill_file(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import get_custom_skill_file

        assert get_custom_skill_file("alpha", tmp_path).name == "SKILL.md"

    def test_custom_skill_exists(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import (
            custom_skill_exists,
            get_custom_skill_file,
            get_public_skill_dir,
            public_skill_exists,
        )

        # Initially no skills.
        assert not custom_skill_exists("alpha", tmp_path)
        assert not public_skill_exists("alpha", tmp_path)
        # Create the custom skill.
        get_custom_skill_file("alpha", tmp_path).parent.mkdir(parents=True, exist_ok=True)
        get_custom_skill_file("alpha", tmp_path).write_text("x", encoding="utf-8")
        assert custom_skill_exists("alpha", tmp_path)
        # Public dir doesn't auto-create; needs manual mkdir.
        (get_public_skill_dir("beta", tmp_path) / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
        (get_public_skill_dir("beta", tmp_path) / "SKILL.md").write_text("y", encoding="utf-8")
        assert public_skill_exists("beta", tmp_path)


class TestEnsureSafeSupportPath:
    def test_rejects_absolute(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import ensure_safe_support_path

        with pytest.raises(ValueError, match="relative"):
            ensure_safe_support_path("alpha", "/etc/passwd", tmp_path)

    def test_rejects_traversal(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import ensure_safe_support_path

        with pytest.raises(ValueError, match="traversal"):
            ensure_safe_support_path("alpha", "../escape.md", tmp_path)

    def test_rejects_trailing_slash(self, tmp_path: Path) -> None:
        from agent_sdk.skills.manager import ensure_safe_support_path

        with pytest.raises(ValueError, match="filename"):
            ensure_safe_support_path("alpha", "references/", tmp_path)

    def test_accepts_any_subdir(self, tmp_path: Path) -> None:
        # Build the expected target directory so resolve() doesn't fail.
        from agent_sdk.skills.manager import ensure_safe_support_path, get_custom_skill_dir

        target = get_custom_skill_dir("alpha", tmp_path) / "references" / "x.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

        resolved = ensure_safe_support_path("alpha", "references/x.md", tmp_path)
        assert resolved == target

    def test_accepts_non_standard_subdir(self, tmp_path: Path) -> None:
        # Any subdirectory should be accepted — not just a fixed whitelist.
        from agent_sdk.skills.manager import ensure_safe_support_path, get_custom_skill_dir

        target = get_custom_skill_dir("alpha", tmp_path) / "workflows" / "generate.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

        resolved = ensure_safe_support_path("alpha", "workflows/generate.md", tmp_path)
        assert resolved == target
