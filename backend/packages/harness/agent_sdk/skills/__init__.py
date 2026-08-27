"""Skills subsystem for agent runtime.

This package is a re-implementation (per ADR-010) of
``deerflow.skills`` — the on-disk convention for storing
"skill" documents (``SKILL.md`` files with YAML
front-matter) that augment the agent's system prompt with
domain-specific workflows.

The :class:`Skill` data class is the brand-neutral
representation; the parser turns a ``SKILL.md`` file into
a :class:`Skill`; the loader scans a directory for skills;
the middleware injects the enabled-skill list into the
agent's system prompt.  The installer (5.5.10) supports
downloading and installing ``.zip`` archives from remote
sources.

Public surface
--------------
* :class:`Skill` — parsed skill (name / description / path / …)
* :func:`parse_skill_file` — turn a ``SKILL.md`` into a :class:`Skill`
* :func:`load_skills` — scan a directory and return a list
* :func:`validate_skill_name` — name pattern check
* :func:`validate_skill_frontmatter` — validate SKILL.md frontmatter (used by installer)
* :class:`SkillsMiddleware` — inject ``<available_skills>`` into the system prompt
* :func:`ainstall_skill_from_archive` / :func:`install_skill_from_archive` — install ``.zip`` archives
"""

from __future__ import annotations

from agent_sdk.skills.installer import (
    SkillAlreadyExistsError,
    SkillSecurityScanError,
    ainstall_skill_from_archive,
    install_skill_from_archive,
    is_symlink_member,
    is_unsafe_zip_member,
    safe_extract_skill_archive,
)
from agent_sdk.skills.loader import load_skills
from agent_sdk.skills.manager import validate_skill_name
from agent_sdk.skills.middleware import SkillsMiddleware
from agent_sdk.skills.parser import parse_skill_file
from agent_sdk.skills.tools import make_skill_tools
from agent_sdk.skills.types import Skill
from agent_sdk.skills.validation import (
    ALLOWED_FRONTMATTER_PROPERTIES,
    validate_skill_frontmatter,
)

__all__ = [
    "ALLOWED_FRONTMATTER_PROPERTIES",
    "Skill",
    "SkillAlreadyExistsError",
    "SkillSecurityScanError",
    "SkillsMiddleware",
    "ainstall_skill_from_archive",
    "make_skill_tools",
    "install_skill_from_archive",
    "is_symlink_member",
    "is_unsafe_zip_member",
    "load_skills",
    "parse_skill_file",
    "safe_extract_skill_archive",
    "validate_skill_frontmatter",
    "validate_skill_name",
]
