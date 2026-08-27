"""SKILL.md parser — extract YAML front-matter into a :class:`Skill` instance.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.parser.parse_skill_file``. The parser only
depends on the standard library plus :mod:`pyyaml` (added as
an SDK dependency), so a project that adopts the SDK without
YAML elsewhere will not be forced to take a heavier stack.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from agent_sdk.skills.types import Skill

logger = logging.getLogger(__name__)


# Accept both LF and CRLF line endings so that skills created
# on Windows (or copied with git core.autocrlf=true) are parsed
# correctly without pre-processing.
_FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.DOTALL)

# Pattern for a plain YAML key (hyphen-case identifier followed by colon).
_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*\s*:")


def _auto_indent_continuation(frontmatter_text: str) -> str:
    """Auto-indent unindented continuation lines in YAML frontmatter.

    YAML requires multi-line values to be indented relative to the key.
    When a value's continuation lines are at the same indentation level
    as the key (e.g. a ``description`` whose body lines start at column
    0), YAML will fail to parse.  This function detects such lines and
    adds the necessary indentation so that ``yaml.safe_load`` succeeds.

    Heuristic:
        1. Track the most-recently-seen key that has an inline value.
        2. A subsequent line is treated as a continuation of that key's
           value when it is at the same or shallower indentation as the
           key and does **not** look like a new YAML key definition
           (``word:`` pattern).
        3. Lines that are already indented deeper than the key, empty,
           or block-scalar markers (``|``, ``>``) are left alone.
    """
    lines = frontmatter_text.split("\n")
    result: list[str] = []
    prev_key: str | None = None
    prev_indent = 0
    prev_has_inline = False

    for line in lines:
        stripped = line.strip()

        # ── empty lines reset tracking ──
        if not stripped:
            prev_key = None
            prev_has_inline = False
            result.append(line)
            continue

        indent = len(line) - len(line.lstrip())

        # ── does this line define a new YAML key? ──
        if _KEY_RE.match(stripped):
            prev_key = stripped.split(":", 1)[0].strip()
            prev_indent = indent
            # Inline value present unless the value is a block-scalar indicator.
            value_after = stripped.split(":", 1)[1].strip()
            prev_has_inline = bool(value_after) and value_after not in ("|", ">", "|-", ">-", "|+", ">+")
            result.append(line)
            continue

        # ── continuation of the previous key's inline value? ──
        if prev_key and prev_has_inline and indent <= prev_indent:
            # Auto-indent to prev_indent + 2 so YAML sees it as a continuation.
            result.append(" " * (prev_indent + 2) + stripped)
            continue

        # ── outdent past the key boundary → reset ──
        if indent <= prev_indent:
            prev_key = None
            prev_has_inline = False

        result.append(line)

    return "\n".join(result)


def _try_parse_metadata(frontmatter_text: str, skill_file: Path) -> dict | None:
    """Parse YAML frontmatter with automatic fallback for common formatting issues.

    Returns the parsed metadata dict, or ``None`` when parsing fails
    even after normalisation.
    """
    # Fast path: directly parse.
    try:
        metadata = yaml.safe_load(frontmatter_text)
        if isinstance(metadata, dict):
            return metadata
    except yaml.YAMLError:
        pass

    # Fallback: auto-indent unindented continuation lines and retry.
    try:
        fixed = _auto_indent_continuation(frontmatter_text)
        metadata = yaml.safe_load(fixed)
        if isinstance(metadata, dict):
            logger.debug(
                "Auto-fixed YAML indentation in %s (e.g. unindented multi-line description).",
                skill_file,
            )
            return metadata
    except yaml.YAMLError as exc:
        logger.error("Invalid YAML front-matter in %s (after auto-fix): %s", skill_file, exc)

    return None


def parse_skill_file(skill_file: Path, relative_path: Path | None = None) -> Skill | None:
    """Parse a single ``SKILL.md`` file.

    Args:
        skill_file: Path to the file (must be named ``SKILL.md``).
        relative_path: Relative path from the skills root to
            the skill directory. Defaults to the directory name.

    Returns:
        A :class:`Skill` instance, or ``None`` if the file
        does not exist, is mis-named, lacks a valid YAML
        front-matter, or is missing the required ``name`` /
        ``description`` fields.
    """
    if not skill_file.exists() or skill_file.name != "SKILL.md":
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")

        match = _FRONTMATTER_RE.match(content)
        if not match:
            return None

        metadata = _try_parse_metadata(match.group(1), skill_file)
        if metadata is None:
            return None

        # Required fields.
        name = metadata.get("name")
        description = metadata.get("description")
        if not name or not isinstance(name, str):
            return None
        if not description or not isinstance(description, str):
            return None

        # Normalise whitespace.
        name = name.strip()
        description = description.strip()
        if not name or not description:
            return None

        license_text = metadata.get("license")
        if license_text is not None:
            license_text = str(license_text).strip() or None

        return Skill(
            name=name,
            description=description,
            license=license_text,
            skill_dir=skill_file.parent,
            skill_file=skill_file,
            relative_path=relative_path or Path(skill_file.parent.name),
            enabled=True,  # Real state is set by the loader when the extensions config is present.
        )

    except Exception:
        logger.exception("Unexpected error parsing skill file %s", skill_file)
        return None
