"""Skill data class — the brand-neutral representation of one SKILL.md entry.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.types.Skill``. The fields are the same as
the in-tree reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """A parsed ``SKILL.md`` file plus its on-disk location.

    Attributes:
        name: Skill name from the YAML front-matter (hyphen-case).
        description: Human-readable description (used in the
            ``<available_skills>`` block injected into the
            system prompt).
        license: Optional license string from the front-matter.
        skill_dir: Filesystem path to the skill's directory.
        skill_file: Filesystem path to ``SKILL.md``.
        relative_path: Path of the skill directory relative to
            the skills root (e.g. ``frontend-design``).
        enabled: Whether the skill is currently active. The
            loader updates this from the extensions config
            when it is present.
    """

    name: str
    description: str
    license: str | None
    skill_dir: Path
    skill_file: Path
    relative_path: Path
    enabled: bool = False

    @property
    def skill_path(self) -> str:
        """Posix path of the skill's relative location.

        Returns ``""`` for skills at the skills root, so
        the caller can ``f"{base}/{skill_path}"`` without a
        trailing slash.
        """
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r})"
