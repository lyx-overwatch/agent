"""Skill path helpers and validators.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.manager`` — the thin helper functions that
resolve "where does a custom skill live on disk" without
pulling in the full configuration loader. The SDK version is
**pure-function-only** (no global state) and takes every path
the in-tree reference reads from a config singleton as an
explicit argument, so a project can wire it into any
configuration scheme it likes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: File name for a skill's main metadata document.
SKILL_FILE_NAME = "SKILL.md"

#: Pattern that all skill names must match.
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_skill_name(name: str) -> str:
    """Validate and normalise a skill name.

    Args:
        name: The candidate name (whitespace will be stripped).

    Returns:
        The normalised name.

    Raises:
        ValueError: If the name is empty, too long, or violates
            the hyphen-case pattern.
    """
    normalized = name.strip()
    if not _SKILL_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("Skill name must be hyphen-case using lowercase letters, digits, and hyphens only.")
    if len(normalized) > 64:
        raise ValueError("Skill name must be 64 characters or fewer.")
    return normalized


def get_public_skills_dir(skills_root: Path) -> Path:
    """Return the path to the public (built-in) skills directory."""
    return skills_root / "public"


def get_custom_skills_dir(skills_root: Path) -> Path:
    """Return the path to the custom (user-installed) skills directory.

    The directory is created on disk if it does not yet exist.
    """
    path = skills_root / "custom"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_custom_skill_dir(name: str, skills_root: Path) -> Path:
    """Return the per-skill directory for a custom skill.

    The directory is **not** created — callers can use
    :func:`ensure_custom_skill_is_editable` to verify the
    skill is editable first.
    """
    return get_custom_skills_dir(skills_root) / validate_skill_name(name)


def get_custom_skill_file(name: str, skills_root: Path) -> Path:
    """Return the path to a custom skill's ``SKILL.md``."""
    return get_custom_skill_dir(name, skills_root) / SKILL_FILE_NAME


def get_public_skill_dir(name: str, skills_root: Path) -> Path:
    """Return the per-skill directory for a public (built-in) skill."""
    return get_public_skills_dir(skills_root) / validate_skill_name(name)


def custom_skill_exists(name: str, skills_root: Path) -> bool:
    """Return ``True`` if a custom skill with the given name exists on disk."""
    return get_custom_skill_file(name, skills_root).exists()


def public_skill_exists(name: str, skills_root: Path) -> bool:
    """Return ``True`` if a public skill with the given name exists on disk."""
    return (get_public_skill_dir(name, skills_root) / SKILL_FILE_NAME).exists()


def ensure_safe_support_path(name: str, relative_path: str, skills_root: Path) -> Path:
    """Validate that *relative_path* is a safe supporting-file path.

    Raises:
        ValueError: If the path is empty, ends in a slash, is
            absolute, or contains ``..`` traversal.
    """
    # Path-related checks first — they don't need the skill
    # directory to exist. Name validation runs after, so a
    # caller can hit "absolute path" without first having to
    # produce a syntactically valid skill name.
    if not relative_path or relative_path.endswith("/"):
        raise ValueError("Supporting file path must include a filename.")
    relative = Path(relative_path)
    # Use os.path.isabs to handle POSIX-style paths correctly on
    # Windows (Path('/etc/passwd').is_absolute() is False on Win32
    # because there is no drive letter; os.path.isabs gets this right
    # for both forward-slash and back-slash conventions).
    if os.path.isabs(relative_path):
        raise ValueError("Supporting file path must be relative.")
    if any(part in {"..", ""} for part in relative.parts):
        raise ValueError("Supporting file path must not contain parent-directory traversal.")

    skill_dir = get_custom_skill_dir(name, skills_root).resolve()
    target = (skill_dir / relative).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError as exc:
        raise ValueError("Supporting file path must stay within the skill directory.") from exc
    return target
