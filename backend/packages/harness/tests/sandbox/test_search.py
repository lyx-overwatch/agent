"""Unit tests for :mod:`agent_sdk.sandbox.search`."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from agent_sdk.sandbox.base import GrepMatch
from agent_sdk.sandbox.search import (
    DEFAULT_LINE_SUMMARY_LENGTH,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    IGNORE_PATTERNS,
    find_glob_matches,
    find_grep_matches,
    is_binary_file,
    path_matches,
    should_ignore_name,
    should_ignore_path,
    truncate_line,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_ignore_patterns_is_nonempty(self) -> None:
        assert isinstance(IGNORE_PATTERNS, list)
        assert len(IGNORE_PATTERNS) > 20

    def test_known_entries(self) -> None:
        # Spot-check that the canonical VCS / build entries survived the port.
        for entry in [".git", "__pycache__", "node_modules", "*.log", ".venv"]:
            assert entry in IGNORE_PATTERNS, entry

    def test_default_max_file_size(self) -> None:
        assert DEFAULT_MAX_FILE_SIZE_BYTES == 1_000_000

    def test_default_line_summary(self) -> None:
        assert DEFAULT_LINE_SUMMARY_LENGTH == 200


# ---------------------------------------------------------------------------
# should_ignore_name / should_ignore_path
# ---------------------------------------------------------------------------


class TestShouldIgnore:
    @pytest.mark.parametrize("name", [".git", "node_modules", "__pycache__", ".venv", "build", "*.log"])
    def test_should_ignore_name_matches(self, name: str) -> None:
        assert should_ignore_name(name) is True

    @pytest.mark.parametrize("name", ["src", "main.py", "README.md", "data.json", "src/main.py"])
    def test_should_ignore_name_does_not_match(self, name: str) -> None:
        assert should_ignore_name(name) is False

    def test_should_ignore_path_any_segment(self) -> None:
        assert should_ignore_path("src/.git/config") is True
        assert should_ignore_path("a/b/.venv/bin/python") is True
        assert should_ignore_path("src/main.py") is False

    def test_should_ignore_path_windows_separator(self) -> None:
        assert should_ignore_path("src\\.git\\config") is True


# ---------------------------------------------------------------------------
# path_matches
# ---------------------------------------------------------------------------


class TestPathMatches:
    def test_exact_match(self) -> None:
        assert path_matches("main.py", "main.py") is True

    def test_simple_glob(self) -> None:
        assert path_matches("*.py", "main.py") is True
        assert path_matches("*.py", "main.txt") is False

    def test_double_star(self) -> None:
        assert path_matches("**/*.py", "a/b/c.py") is True
        assert path_matches("**/*.py", "a/b/c.txt") is False

    def test_double_star_root(self) -> None:
        # The implementation strips a leading ``**/`` and re-matches,
        # so a top-level file still matches.
        assert path_matches("**/README.md", "README.md") is True
        assert path_matches("**/README.md", "docs/README.md") is True

    def test_deep_glob(self) -> None:
        # pathlib's ``match`` does not support globstar the way fnmatch does,
        # so the implementation's ``**/`` short-circuit is the supported path.
        assert path_matches("**/*.py", "src/pkg/sub/x.py") is True


# ---------------------------------------------------------------------------
# truncate_line
# ---------------------------------------------------------------------------


class TestTruncateLine:
    def test_short_line_unchanged(self) -> None:
        assert truncate_line("hello") == "hello"

    def test_strips_trailing_newlines(self) -> None:
        assert truncate_line("hello\n") == "hello"
        assert truncate_line("hello\r\n") == "hello"
        assert truncate_line("hello\r") == "hello"

    def test_long_line_truncated_with_ellipsis(self) -> None:
        long = "x" * 500
        out = truncate_line(long, max_chars=50)
        assert out.endswith("...")
        # 50 - 3 = 47 'x' chars + "..." suffix = 50 chars total.
        assert len(out) == 50

    def test_exact_length_unchanged(self) -> None:
        s = "x" * 200
        assert truncate_line(s) == s


# ---------------------------------------------------------------------------
# is_binary_file
# ---------------------------------------------------------------------------


class TestIsBinaryFile:
    def test_text_file(self, tmp_path: Path) -> None:
        p = tmp_path / "a.txt"
        p.write_text("hello world\n", encoding="utf-8")
        assert is_binary_file(p) is False

    def test_binary_file(self, tmp_path: Path) -> None:
        p = tmp_path / "a.bin"
        p.write_bytes(b"\x00\x01\x02binary\x00data")
        assert is_binary_file(p) is True

    def test_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing"
        # OSError -> True (treated as binary to skip).
        assert is_binary_file(p) is True


# ---------------------------------------------------------------------------
# find_glob_matches
# ---------------------------------------------------------------------------


class TestFindGlobMatches:
    def test_basic_match(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        matches, truncated = find_glob_matches(tmp_path, "*.py")
        assert not truncated
        names = sorted(Path(m).name for m in matches)
        assert names == ["a.py", "b.py"]

    def test_recursive_match(self, tmp_path: Path) -> None:
        (tmp_path / "x.py").write_text("")
        nested = tmp_path / "sub" / "deep"
        nested.mkdir(parents=True)
        (nested / "y.py").write_text("")
        matches, _ = find_glob_matches(tmp_path, "**/*.py")
        names = sorted(Path(m).name for m in matches)
        assert names == ["x.py", "y.py"]

    def test_ignores_vcs(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "x.py").write_text("")
        matches, _ = find_glob_matches(tmp_path, "**/*.py")
        names = [Path(m).name for m in matches]
        assert names == ["ok.py"]

    def test_include_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("")
        # Default (files only) does not include the dir.
        matches, _ = find_glob_matches(tmp_path, "**/*")
        names = [Path(m).name for m in matches]
        assert "sub" not in names
        # With include_dirs, the dir is included.
        matches, _ = find_glob_matches(tmp_path, "**/*", include_dirs=True)
        names = [Path(m).name for m in matches]
        assert "sub" in names

    def test_max_results_truncates(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("")
        matches, truncated = find_glob_matches(tmp_path, "*.py", max_results=3)
        assert len(matches) == 3
        assert truncated is True

    def test_missing_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find_glob_matches(tmp_path / "missing", "*.py")

    def test_root_is_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("")
        with pytest.raises(NotADirectoryError):
            find_glob_matches(f, "*")


# ---------------------------------------------------------------------------
# find_grep_matches
# ---------------------------------------------------------------------------


class TestFindGrepMatches:
    def test_basic_regex(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("hello world\nfoo bar\nhello again\n", encoding="utf-8")
        matches, truncated = find_grep_matches(tmp_path, "hello")
        assert not truncated
        assert len(matches) == 2
        assert all(isinstance(m, GrepMatch) for m in matches)
        assert matches[0].line_number == 1
        assert matches[0].line == "hello world"
        assert matches[1].line_number == 3

    def test_literal_mode(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("func() { call(); }\n", encoding="utf-8")
        # Regex mode: ``(`` is a group-open.
        matches, _ = find_grep_matches(tmp_path, "func()", literal=False)
        # In regex, "func()" matches the literal "func()".
        assert len(matches) == 1
        # Literal mode: special regex chars are escaped.
        matches, _ = find_grep_matches(tmp_path, "func()", literal=True)
        assert len(matches) == 1

    def test_case_sensitive(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("Hello\nhello\nHELLO\n", encoding="utf-8")
        # Case insensitive (default).
        matches, _ = find_grep_matches(tmp_path, "hello")
        assert len(matches) == 3
        # Case sensitive.
        matches, _ = find_grep_matches(tmp_path, "hello", case_sensitive=True)
        assert len(matches) == 1
        assert matches[0].line == "hello"

    def test_glob_filter(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("needle\n")
        (tmp_path / "a.txt").write_text("needle\n")
        matches, _ = find_grep_matches(tmp_path, "needle", glob_pattern="*.py")
        assert len(matches) == 1
        assert matches[0].path.endswith("a.py")

    def test_skips_binary(self, tmp_path: Path) -> None:
        (tmp_path / "binary.bin").write_bytes(b"\x00needle\x00data")
        (tmp_path / "text.txt").write_text("needle\n", encoding="utf-8")
        matches, _ = find_grep_matches(tmp_path, "needle")
        names = [Path(m.path).name for m in matches]
        assert names == ["text.txt"]

    def test_skips_oversize(self, tmp_path: Path) -> None:
        big = tmp_path / "big.txt"
        # 1 MB+1 of repeated content.
        big.write_text("needle\n" + "x" * 1_000_001, encoding="utf-8")
        small = tmp_path / "small.txt"
        small.write_text("needle\n", encoding="utf-8")
        matches, _ = find_grep_matches(tmp_path, "needle")
        names = [Path(m.path).name for m in matches]
        assert "small.txt" in names
        assert "big.txt" not in names

    def test_skips_symlinks_outside_root(self, tmp_path: Path) -> None:
        # Symlink creation requires elevated privileges on Windows; skip if unavailable.
        if sys.platform == "win32":
            pytest.skip("symlink creation requires elevated privileges on Windows")
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("needle\n", encoding="utf-8")
        try:
            (tmp_path / "link.txt").symlink_to(outside)
            matches, _ = find_grep_matches(tmp_path, "needle")
            assert matches == []
        finally:
            outside.unlink(missing_ok=True)

    def test_skips_long_lines(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x" * 5000 + "needle\n", encoding="utf-8")
        matches, _ = find_grep_matches(tmp_path, "needle", line_summary_length=200)
        # Line > 200*10 = 2000 chars -> skipped.
        assert matches == []

    def test_max_results_truncates(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("\n".join(f"hit {i}" for i in range(20)), encoding="utf-8")
        matches, truncated = find_grep_matches(tmp_path, "hit", max_results=5)
        assert len(matches) == 5
        assert truncated is True

    def test_long_line_truncated_in_match(self, tmp_path: Path) -> None:
        # Line must be <= line_summary_length*10 = 500 chars to avoid the
        # ReDoS guard, but longer than line_summary_length to be truncated.
        line = "needle" + "x" * 100  # 106 chars
        (tmp_path / "a.py").write_text(line + "\n", encoding="utf-8")
        matches, _ = find_grep_matches(tmp_path, "needle", line_summary_length=50)
        assert len(matches) == 1
        # Truncated to 50 chars with "..." suffix.
        assert len(matches[0].line) == 50
        assert matches[0].line.endswith("...")

    def test_ignores_vcs_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "ok.py").write_text("needle\n", encoding="utf-8")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "x.py").write_text("needle\n", encoding="utf-8")
        matches, _ = find_grep_matches(tmp_path, "needle")
        names = [Path(m.path).relative_to(tmp_path).parts[0] for m in matches]
        assert names == ["ok.py"]

    def test_invalid_regex_raises(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("anything\n", encoding="utf-8")
        with pytest.raises(re.error):
            find_grep_matches(tmp_path, "(unclosed")

    def test_missing_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find_grep_matches(tmp_path / "missing", "x")
