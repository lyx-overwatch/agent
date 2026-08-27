"""Filesystem search helpers (glob / grep) shared by sandbox implementations.

This module is a re-implementation (per ADR-010) of
``deerflow.sandbox.search``. The helpers are pure-Python and
**brand-neutral** — they have no business assumptions (no
DeerFlow paths, no config reads) and can be reused by any
:class:`agent_sdk.sandbox.Sandbox` implementation that needs
host-side file walking.

Two main entry points:

* :func:`find_glob_matches` — recursive file/directory matcher
  with VCS-friendly ignore patterns and ``max_results`` cap.
* :func:`find_grep_matches` — recursive text search with
  regex / literal modes, optional secondary glob filter, file
  size and binary guards, and ``max_results`` cap.

Both return ``(matches, truncated)`` to match the
:class:`agent_sdk.sandbox.Sandbox` ABC contract.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePosixPath

from agent_sdk.sandbox.base import GrepMatch

#: Default cap on per-file size considered by grep (bytes).
#: Mirrors the backend constant.
DEFAULT_MAX_FILE_SIZE_BYTES = 1_000_000

#: Default cap on per-line length stored in a :class:`GrepMatch`
#: (characters). The match walker also uses this * 10 as the
#: "skip absurdly long lines" threshold (ReDoS guard).
DEFAULT_LINE_SUMMARY_LENGTH = 200

#: VCS / build / IDE artefacts to skip during file walks.
#: Mirrors the backend's list byte-for-byte.
IGNORE_PATTERNS = [
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "env",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "site-packages",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".output",
    ".turbo",
    "target",
    "out",
    ".idea",
    ".vscode",
    "*.swp",
    "*.swo",
    "*~",
    ".project",
    ".classpath",
    ".settings",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.lnk",
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.cache",
    ".cache",
    "logs",
    ".coverage",
    "coverage",
    ".nyc_output",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]


def should_ignore_name(name: str) -> bool:
    """Return ``True`` if *name* matches any :data:`IGNORE_PATTERNS` entry."""
    for pattern in IGNORE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def should_ignore_path(path: str) -> bool:
    """Return ``True`` if any segment of *path* matches the ignore list."""
    return any(should_ignore_name(segment) for segment in path.replace("\\", "/").split("/") if segment)


def path_matches(pattern: str, rel_path: str) -> bool:
    """Match a glob *pattern* against a POSIX *rel_path*.

    Two-stage match: first against the full path, then against
    the path with a leading ``**/`` stripped from the pattern.
    """
    path = PurePosixPath(rel_path)
    if path.match(pattern):
        return True
    if pattern.startswith("**/"):
        return path.match(pattern[3:])
    return False


def truncate_line(line: str, max_chars: int = DEFAULT_LINE_SUMMARY_LENGTH) -> str:
    """Strip trailing newlines and cap a line at *max_chars* characters."""
    line = line.rstrip("\n\r")
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 3] + "..."


def is_binary_file(path: Path, sample_size: int = 8192) -> bool:
    """Sniff the first *sample_size* bytes of *path* for a NUL byte.

    Returns ``True`` (treated as binary) on any
    :class:`OSError` — the file walker skips such files.
    """
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(sample_size)
    except OSError:
        return True


def find_glob_matches(
    root: Path,
    pattern: str,
    *,
    include_dirs: bool = False,
    max_results: int = 200,
) -> tuple[list[str], bool]:
    """Walk *root* and return paths matching the glob *pattern*.

    Args:
        root: Resolved directory to walk.
        pattern: Glob pattern, relative to *root*.
        include_dirs: When ``True``, also include matching
            directories. Default is files only.
        max_results: Cap on the number of returned matches.

    Returns:
        A ``(matches, truncated)`` tuple. ``truncated`` is
        ``True`` if the walker stopped at *max_results*.

    Raises:
        FileNotFoundError: If *root* does not exist.
        NotADirectoryError: If *root* is not a directory.
    """
    matches: list[str] = []
    truncated = False
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not should_ignore_name(name)]
        # root is already resolved; os.walk builds current_root by joining under root,
        # so relative_to() works without an extra stat()/resolve() per directory.
        rel_dir = Path(current_root).relative_to(root)

        if include_dirs:
            for name in dirs:
                rel_path = (rel_dir / name).as_posix()
                if path_matches(pattern, rel_path):
                    matches.append(str(Path(current_root) / name))
                    if len(matches) >= max_results:
                        truncated = True
                        return matches, truncated

        for name in files:
            if should_ignore_name(name):
                continue
            rel_path = (rel_dir / name).as_posix()
            if path_matches(pattern, rel_path):
                matches.append(str(Path(current_root) / name))
                if len(matches) >= max_results:
                    truncated = True
                    return matches, truncated

    return matches, truncated


def find_grep_matches(
    root: Path,
    pattern: str,
    *,
    glob_pattern: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    line_summary_length: int = DEFAULT_LINE_SUMMARY_LENGTH,
) -> tuple[list[GrepMatch], bool]:
    """Walk *root* and return regex matches in text files.

    Args:
        root: Resolved directory to walk.
        pattern: Regex source when ``literal=False``; literal
            substring when ``literal=True``.
        glob_pattern: Optional secondary glob filter applied
            to each candidate file's POSIX-relative path.
        literal: Treat *pattern* as a literal substring.
        case_sensitive: When ``False`` (default), the search
            is case-insensitive.
        max_results: Cap on the number of returned matches.
        max_file_size: Per-file size limit (bytes). Larger
            files are skipped.
        line_summary_length: Per-match line cap (chars) and
            also drives the per-line ReDoS guard (lines longer
            than ``line_summary_length * 10`` are skipped).

    Returns:
        A ``(matches, truncated)`` tuple. ``truncated`` is
        ``True`` if the walker stopped at *max_results*.

    Raises:
        FileNotFoundError: If *root* does not exist.
        NotADirectoryError: If *root* is not a directory.
    """
    matches: list[GrepMatch] = []
    truncated = False
    root = root.resolve()

    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    regex_source = re.escape(pattern) if literal else pattern
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(regex_source, flags)

    # Skip lines longer than this to prevent ReDoS on minified / no-newline files.
    _max_line_chars = line_summary_length * 10

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not should_ignore_name(name)]
        rel_dir = Path(current_root).relative_to(root)

        for name in files:
            if should_ignore_name(name):
                continue

            candidate_path = Path(current_root) / name
            rel_path = (rel_dir / name).as_posix()

            if glob_pattern is not None and not path_matches(glob_pattern, rel_path):
                continue

            try:
                if candidate_path.is_symlink():
                    continue
                file_path = candidate_path.resolve()
                if not file_path.is_relative_to(root):
                    continue
                if file_path.stat().st_size > max_file_size or is_binary_file(file_path):
                    continue
                with file_path.open(encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if len(line) > _max_line_chars:
                            continue
                        if regex.search(line):
                            matches.append(
                                GrepMatch(
                                    path=str(file_path),
                                    line_number=line_number,
                                    line=truncate_line(line, line_summary_length),
                                )
                            )
                            if len(matches) >= max_results:
                                truncated = True
                                return matches, truncated
            except OSError:
                continue

    return matches, truncated


__all__ = [
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_LINE_SUMMARY_LENGTH",
    "GrepMatch",
    "IGNORE_PATTERNS",
    "find_glob_matches",
    "find_grep_matches",
    "is_binary_file",
    "path_matches",
    "should_ignore_name",
    "should_ignore_path",
    "truncate_line",
]
