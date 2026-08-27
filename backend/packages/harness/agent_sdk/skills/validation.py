"""Skill frontmatter validation utilities.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.validation``. It is pure-logic validation
of SKILL.md frontmatter — no FastAPI, HTTP, or config
dependencies.

The functions are used by :mod:`agent_sdk.skills.installer`
to validate skill archives before installation.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

#: Allowed top-level keys in SKILL.md frontmatter.
ALLOWED_FRONTMATTER_PROPERTIES: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "license",
        "allowed-tools",
        "metadata",
        "compatibility",
        "version",
        "author",
    }
)

#: Maximum skill name length (same as backend).
_MAX_NAME_LENGTH = 64

#: Maximum description length (same as backend).
_MAX_DESCRIPTION_LENGTH = 1024


def validate_skill_frontmatter(skill_dir: Path) -> tuple[bool, str, str | None]:
    """Validate a skill directory's SKILL.md frontmatter.

    Args:
        skill_dir: Path to the skill directory containing SKILL.md.

    Returns:
        Tuple of ``(is_valid, message, skill_name)``. When
        ``is_valid`` is ``True``, *skill_name* is the parsed
        name from the frontmatter; otherwise *skill_name* is
        ``None``.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found", None

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "No YAML frontmatter found", None

    # Extract frontmatter
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format", None

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary", None
    except yaml.YAMLError as e:
        return False, f"Invalid YAML in frontmatter: {e}", None

    # Check for unexpected properties
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_FRONTMATTER_PROPERTIES
    if unexpected_keys:
        return (
            False,
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}",
            None,
        )

    # Check required fields
    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter", None
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter", None

    # Validate name
    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}", None
    name = name.strip()
    if not name:
        return False, "Name cannot be empty", None

    # Check naming convention (hyphen-case: lowercase with hyphens)
    if not re.match(r"^[a-z0-9-]+$", name):
        return (
            False,
            f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)",
            None,
        )
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return (
            False,
            f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens",
            None,
        )
    if len(name) > _MAX_NAME_LENGTH:
        return (
            False,
            f"Name is too long ({len(name)} characters). Maximum is {_MAX_NAME_LENGTH} characters.",
            None,
        )

    # Validate description
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}", None
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "Description cannot contain angle brackets (< or >)", None
        if len(description) > _MAX_DESCRIPTION_LENGTH:
            return (
                False,
                f"Description is too long ({len(description)} characters). Maximum is {_MAX_DESCRIPTION_LENGTH} characters.",
                None,
            )

    return True, "Skill is valid!", name


def parse_skill_frontmatter(skill_dir: Path) -> dict:
    """Extract and YAML-parse the SKILL.md frontmatter, returning the raw dict.

    Callers should already have run :func:`validate_skill_frontmatter`; this
    function performs no field-level validation and raises ``ValueError`` if
    the frontmatter is missing or malformed.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise ValueError("SKILL.md not found")

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError("No YAML frontmatter found")

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        raise ValueError("Invalid frontmatter format")

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(frontmatter, dict):
        raise ValueError("Frontmatter must be a YAML dictionary")
    return frontmatter
