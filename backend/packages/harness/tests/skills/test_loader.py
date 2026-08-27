"""Unit tests for :func:`agent_sdk.skills.loader.load_skills`."""

from __future__ import annotations

from pathlib import Path


def _write_skill(category_dir: Path, name: str, description: str = "d") -> None:
    skill_dir = category_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


class TestLoadSkills:
    def test_returns_empty_when_root_missing(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        assert load_skills(tmp_path / "missing") == []

    def test_scans_public_and_custom(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "alpha", "public skill")
        _write_skill(tmp_path / "custom", "beta", "custom skill")
        skills = load_skills(tmp_path)
        names = {s.name for s in skills}
        assert names == {"alpha", "beta"}
        # Top-level sub-directory is captured in relative_path.
        assert {s.relative_path.parts[0] for s in skills} == {"public", "custom"}

    def test_results_are_sorted_by_name(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        for n in ["zebra", "alpha", "mango"]:
            _write_skill(tmp_path / "public", n)
        skills = load_skills(tmp_path)
        assert [s.name for s in skills] == ["alpha", "mango", "zebra"]

    def test_skips_subdirs_without_skill_md(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "real")
        (tmp_path / "public" / "fake").mkdir()  # no SKILL.md
        skills = load_skills(tmp_path)
        assert {s.name for s in skills} == {"real"}

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "real")
        (tmp_path / "public" / ".hidden").mkdir()
        (tmp_path / "public" / ".hidden" / "SKILL.md").write_text(
            "---\nname: hidden\ndescription: d\n---\n", encoding="utf-8"
        )
        skills = load_skills(tmp_path)
        assert {s.name for s in skills} == {"real"}

    def test_skips_invalid_skill_files(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "good")
        bad = tmp_path / "public" / "bad" / "SKILL.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("no front matter\n", encoding="utf-8")
        skills = load_skills(tmp_path)
        assert {s.name for s in skills} == {"good"}

    def test_enabled_filter_callback(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "alpha")
        _write_skill(tmp_path / "public", "beta")
        skills = load_skills(tmp_path, is_enabled=lambda name: name == "alpha")
        # Both skills are returned; only "alpha" is marked enabled.
        assert {s.name for s in skills} == {"alpha", "beta"}
        by_name = {s.name: s.enabled for s in skills}
        assert by_name == {"alpha": True, "beta": False}

    def test_enabled_filter_set(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "alpha")
        _write_skill(tmp_path / "public", "beta")
        skills = load_skills(tmp_path, enabled_names={"alpha"})
        assert {s.name for s in skills if s.enabled} == {"alpha"}

    def test_enabled_only_filters(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        _write_skill(tmp_path / "public", "alpha")
        _write_skill(tmp_path / "public", "beta")
        skills = load_skills(tmp_path, enabled_only=True, enabled_names={"alpha"})
        assert {s.name for s in skills} == {"alpha"}

    def test_custom_categories(self, tmp_path: Path) -> None:
        from agent_sdk.skills.loader import load_skills

        (tmp_path / "experimental").mkdir()
        _write_skill(tmp_path / "experimental", "x")
        skills = load_skills(tmp_path)
        assert {s.name for s in skills} == {"x"}
        assert {s.relative_path.parts[0] for s in skills} == {"experimental"}
