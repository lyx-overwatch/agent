"""Unit tests for :mod:`agent_sdk.skills.installer`."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_skill_zip(
    target: Path,
    name: str = "my-skill",
    description: str = "A test skill",
    *,
    extra_files: dict[str, str] | None = None,
) -> None:
    """Create a valid ``.zip`` ZIP archive."""
    skill_md = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", skill_md)
        if extra_files:
            for rel_path, content in extra_files.items():
                zf.writestr(f"{name}/{rel_path}", content)


def _make_skills_root(tmp_path: Path) -> Path:
    """Create a skills root with a custom/ sub-directory."""
    root = tmp_path / "skills"
    root.mkdir()
    (root / "custom").mkdir()
    return root


# ------------------------------------------------------------------
# is_unsafe_zip_member
# ------------------------------------------------------------------


class TestIsUnsafeZipMember:
    def test_safe_path(self) -> None:
        from agent_sdk.skills.installer import is_unsafe_zip_member

        info = zipfile.ZipInfo("my-skill/SKILL.md")
        assert is_unsafe_zip_member(info) is False

    def test_absolute_path(self) -> None:
        from agent_sdk.skills.installer import is_unsafe_zip_member

        info = zipfile.ZipInfo("/etc/passwd")
        assert is_unsafe_zip_member(info) is True

    def test_parent_traversal(self) -> None:
        from agent_sdk.skills.installer import is_unsafe_zip_member

        info = zipfile.ZipInfo("../outside/file.txt")
        assert is_unsafe_zip_member(info) is True

    def test_empty_name(self) -> None:
        from agent_sdk.skills.installer import is_unsafe_zip_member

        info = zipfile.ZipInfo("")
        assert is_unsafe_zip_member(info) is False

    def test_windows_absolute(self) -> None:
        from agent_sdk.skills.installer import is_unsafe_zip_member

        info = zipfile.ZipInfo("C:\\Windows\\file.txt")
        assert is_unsafe_zip_member(info) is True


# ------------------------------------------------------------------
# safe_extract_skill_archive
# ------------------------------------------------------------------


class TestSafeExtractSkillArchive:
    def test_extracts_valid_archive(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import safe_extract_skill_archive

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="my-skill")
        dest = tmp_path / "extracted"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_skill_archive(zf, dest)

        assert (dest / "my-skill" / "SKILL.md").exists()

    def test_rejects_unsafe_path(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import safe_extract_skill_archive

        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../escape/SKILL.md", "---\nname: x\ndescription: d\n---\n")

        dest = tmp_path / "extracted"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, "r") as zf:
            with pytest.raises(ValueError, match="unsafe"):
                safe_extract_skill_archive(zf, dest)

    def test_size_limit_exceeded(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import safe_extract_skill_archive

        zip_path = tmp_path / "big.zip"
        _make_skill_zip(
            zip_path,
            name="big",
            extra_files={"data.txt": "x" * 1000},
        )

        dest = tmp_path / "extracted"
        dest.mkdir()

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Very small limit — should trip immediately.
            with pytest.raises(ValueError, match="too large"):
                safe_extract_skill_archive(zf, dest, max_total_size=1)


# ------------------------------------------------------------------
# _default_scan_content
# ------------------------------------------------------------------


class TestDefaultScanContent:
    async def test_allows_non_executable(self) -> None:
        from agent_sdk.skills.installer import _default_scan_content

        result = await _default_scan_content("safe content", executable=False, location="test/SKILL.md")
        assert result.decision == "allow"

    async def test_blocks_executable(self) -> None:
        from agent_sdk.skills.installer import _default_scan_content

        result = await _default_scan_content(
            "#!/bin/bash\necho hi", executable=True, location="test/scripts/run.sh"
        )
        assert result.decision == "block"


# ------------------------------------------------------------------
# ainstall_skill_from_archive
# ------------------------------------------------------------------


class TestAinstallSkillFromArchive:
    async def test_installs_valid_skill(self, tmp_path: Path) -> None:

        from agent_sdk.skills.installer import ainstall_skill_from_archive

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="my-skill", description="A test skill")
        skills_root = _make_skills_root(tmp_path)

        result = await ainstall_skill_from_archive(
            zip_path, skills_root=skills_root
        )
        assert result["success"] is True
        assert result["skill_name"] == "my-skill"

        # Verify the skill directory was created.
        installed = skills_root / "custom" / "my-skill"
        assert installed.exists()
        assert (installed / "SKILL.md").exists()

    async def test_file_not_found(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        skills_root = _make_skills_root(tmp_path)
        with pytest.raises(FileNotFoundError):
            await ainstall_skill_from_archive(
                tmp_path / "nonexistent.zip", skills_root=skills_root
            )

    async def test_wrong_extension(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        not_zip = tmp_path / "test.txt"
        not_zip.write_text("not a zip")
        skills_root = _make_skills_root(tmp_path)

        with pytest.raises(ValueError, match=".zip extension"):
            await ainstall_skill_from_archive(not_zip, skills_root=skills_root)

    async def test_invalid_zip(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_text("not a zip file at all")
        skills_root = _make_skills_root(tmp_path)

        with pytest.raises(ValueError, match="not a valid ZIP"):
            await ainstall_skill_from_archive(bad_zip, skills_root=skills_root)

    async def test_duplicate_name(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import (
            SkillAlreadyExistsError,
            ainstall_skill_from_archive,
        )

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="my-skill")
        skills_root = _make_skills_root(tmp_path)

        # First install.
        await ainstall_skill_from_archive(zip_path, skills_root=skills_root)

        # Second install should fail.
        with pytest.raises(SkillAlreadyExistsError, match="already exists"):
            await ainstall_skill_from_archive(zip_path, skills_root=skills_root)

    async def test_invalid_frontmatter(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        zip_path = tmp_path / "bad.zip"
        # Create a skill with no name.
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("bad/SKILL.md", "---\ndescription: d\n---\n")

        skills_root = _make_skills_root(tmp_path)
        with pytest.raises(ValueError, match="Invalid skill"):
            await ainstall_skill_from_archive(zip_path, skills_root=skills_root)

    async def test_name_with_slashes_rejected(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        zip_path = tmp_path / "bad.zip"
        _make_skill_zip(zip_path, name="path/traversal")
        skills_root = _make_skills_root(tmp_path)

        with pytest.raises(ValueError, match="Invalid skill"):
            await ainstall_skill_from_archive(zip_path, skills_root=skills_root)

    async def test_custom_scanner_allows(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import ainstall_skill_from_archive

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="scanned")
        skills_root = _make_skills_root(tmp_path)

        async def _allow_all(content, executable, location):
            from agent_sdk.skills.installer import _ScanResult
            return _ScanResult("allow", "ok")

        result = await ainstall_skill_from_archive(
            zip_path, skills_root=skills_root, scan_content=_allow_all
        )
        assert result["success"] is True
        assert result["skill_name"] == "scanned"

    async def test_custom_scanner_blocks_skill_md(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import (
            SkillSecurityScanError,
            ainstall_skill_from_archive,
        )

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="blocked")
        skills_root = _make_skills_root(tmp_path)

        async def _block_skill_md(content, executable, location):
            from agent_sdk.skills.installer import _ScanResult
            if "SKILL.md" in location:
                return _ScanResult("block", "not allowed")
            return _ScanResult("allow", "ok")

        with pytest.raises(SkillSecurityScanError, match="blocked skill"):
            await ainstall_skill_from_archive(
                zip_path, skills_root=skills_root, scan_content=_block_skill_md
            )

    async def test_custom_scanner_blocks_script(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import (
            SkillSecurityScanError,
            ainstall_skill_from_archive,
        )

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(
            zip_path,
            name="scripted",
            extra_files={"scripts/run.sh": "#!/bin/bash\necho hi"},
        )
        skills_root = _make_skills_root(tmp_path)

        async def _block_scripts(content, executable, location):
            from agent_sdk.skills.installer import _ScanResult
            if executable:
                return _ScanResult("block", "scripts not allowed")
            return _ScanResult("allow", "ok")

        with pytest.raises(SkillSecurityScanError, match="Security scan blocked"):
            await ainstall_skill_from_archive(
                zip_path, skills_root=skills_root, scan_content=_block_scripts
            )

    async def test_custom_scanner_rejects_executable(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import (
            SkillSecurityScanError,
            ainstall_skill_from_archive,
        )

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(
            zip_path,
            name="scripted",
            extra_files={"scripts/run.sh": "#!/bin/bash\necho hi"},
        )
        skills_root = _make_skills_root(tmp_path)

        async def _warn_scripts(content, executable, location):
            from agent_sdk.skills.installer import _ScanResult
            if executable:
                return _ScanResult("warn", "be careful")
            return _ScanResult("allow", "ok")

        # A "warn" decision on executable content should still reject it.
        with pytest.raises(SkillSecurityScanError, match="rejected executable"):
            await ainstall_skill_from_archive(
                zip_path, skills_root=skills_root, scan_content=_warn_scripts
            )

    async def test_nested_skill_md_raises(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import (
            SkillSecurityScanError,
            ainstall_skill_from_archive,
        )

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("nested/SKILL.md", "---\nname: nested\ndescription: d\n---\n")
            zf.writestr(
                "nested/sub/SKILL.md", "---\nname: inner\ndescription: d\n---\n"
            )

        skills_root = _make_skills_root(tmp_path)

        async def _scan(content, executable, location):
            from agent_sdk.skills.installer import _ScanResult
            return _ScanResult("allow", "ok")

        with pytest.raises(SkillSecurityScanError, match="nested SKILL.md"):
            await ainstall_skill_from_archive(
                zip_path, skills_root=skills_root, scan_content=_scan
            )


# ------------------------------------------------------------------
# Sync wrapper
# ------------------------------------------------------------------


class TestInstallSkillFromArchive:
    def test_sync_wrapper_works(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import install_skill_from_archive

        zip_path = tmp_path / "test.zip"
        _make_skill_zip(zip_path, name="sync-skill")
        skills_root = _make_skills_root(tmp_path)

        result = install_skill_from_archive(zip_path, skills_root=skills_root)
        assert result["success"] is True
        assert result["skill_name"] == "sync-skill"


# ------------------------------------------------------------------
# resolve_skill_dir_from_archive
# ------------------------------------------------------------------


class TestResolveSkillDirFromArchive:
    def test_single_subdir_returns_it(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import _resolve_skill_dir_from_archive

        (tmp_path / "my-skill").mkdir()
        (tmp_path / "my-skill" / "SKILL.md").write_text("x")
        result = _resolve_skill_dir_from_archive(tmp_path)
        assert result.name == "my-skill"

    def test_multiple_files_returns_root(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import _resolve_skill_dir_from_archive

        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("b")
        result = _resolve_skill_dir_from_archive(tmp_path)
        assert result == tmp_path

    def test_empty_archive_raises(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import _resolve_skill_dir_from_archive

        with pytest.raises(ValueError, match="empty"):
            _resolve_skill_dir_from_archive(tmp_path)

    def test_filters_macos_metadata(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import _resolve_skill_dir_from_archive

        (tmp_path / "__MACOSX").mkdir()
        (tmp_path / ".DS_Store").write_text("x")
        with pytest.raises(ValueError, match="empty"):
            _resolve_skill_dir_from_archive(tmp_path)

    def test_multiple_top_level_skills_raises(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import MultiSkillArchiveError, _resolve_skill_dir_from_archive

        for name in ("skill-a", "skill-b", "skill-c"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "SKILL.md").write_text("x")
        with pytest.raises(MultiSkillArchiveError) as exc_info:
            _resolve_skill_dir_from_archive(tmp_path)
        assert set(exc_info.value.skill_names) == {"skill-a", "skill-b", "skill-c"}

    def test_wrapper_dir_with_multiple_skills_raises(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import MultiSkillArchiveError, _resolve_skill_dir_from_archive

        wrapper = tmp_path / "my-bundle"
        for name in ("skill-a", "skill-b"):
            (wrapper / name).mkdir(parents=True)
            (wrapper / name / "SKILL.md").write_text("x")
        with pytest.raises(MultiSkillArchiveError) as exc_info:
            _resolve_skill_dir_from_archive(tmp_path)
        assert set(exc_info.value.skill_names) == {"skill-a", "skill-b"}

    def test_nested_skill_md_is_not_multi_skill(self, tmp_path: Path) -> None:
        from agent_sdk.skills.installer import _resolve_skill_dir_from_archive

        # A single skill with a nested SKILL.md should NOT be reported as
        # multi-skill — it has only one topmost root and is handled by the
        # security scanner later.
        (tmp_path / "my-skill").mkdir()
        (tmp_path / "my-skill" / "SKILL.md").write_text("x")
        (tmp_path / "my-skill" / "sub").mkdir()
        (tmp_path / "my-skill" / "sub" / "SKILL.md").write_text("x")
        result = _resolve_skill_dir_from_archive(tmp_path)
        assert result.name == "my-skill"
