"""Skill loader — scan a skills root and return parsed :class:`Skill` instances.

This module is a re-implementation (per ADR-010) of
``deerflow.skills.loader.load_skills``. The SDK version is
**pure-function-only** (no global state) and takes every path
as an explicit argument.

Optional filtering
------------------
The loader accepts two orthogonal ways to express "which
skills are enabled":

* a *callback* ``is_enabled(name) -> bool`` —
  preferred when the project already has an enable/disable
  policy (e.g. an extensions config);
* a *set* of enabled names — convenience for tests and
  small deployments.

When neither is supplied, every parsed skill is returned
with ``enabled=True`` (the parser default).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from agent_sdk.skills.parser import parse_skill_file
from agent_sdk.skills.types import Skill

logger = logging.getLogger(__name__)

#: Callback signature for an external enable/disable policy.
EnabledFilter = Callable[[str], bool]


def load_skills(
    skills_path: Path,
    *,
    enabled_only: bool = False,
    is_enabled: EnabledFilter | None = None,
    enabled_names: set[str] | None = None,
) -> list[Skill]:
    """Scan *skills_path* and return parsed :class:`Skill` instances.

    Args:
        skills_path: Root directory that contains skill sub-directories.
        enabled_only: If ``True``, drop skills whose
            :attr:`Skill.enabled` is ``False`` after the
            filter is applied.
        is_enabled: Optional callback ``(name) -> bool``
            used to mark each parsed skill.
        enabled_names: Optional set of names; any skill whose
            ``name`` is **not** in the set is marked disabled.

    Returns:
        A list of :class:`Skill` instances sorted by name
        (stable order — useful for golden snapshots and
        deterministic LLM context).
    """
    if not skills_path.exists():
        return []

    skills_by_name: dict[str, Skill] = {}

    for current_root, dir_names, file_names in os.walk(skills_path):
        # Keep traversal deterministic and skip hidden directories.
        dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
        if "SKILL.md" not in file_names:
            continue

        skill_file = Path(current_root) / "SKILL.md"
        relative_path = skill_file.parent.relative_to(skills_path)
        skill = parse_skill_file(skill_file, relative_path=relative_path)
        if skill is None:
            continue
        skills_by_name[skill.name] = skill

    # Apply the enable/disable filter.
    for skill in skills_by_name.values():
        if is_enabled is not None:
            try:
                skill.enabled = bool(is_enabled(skill.name))
            except Exception:
                logger.warning("is_enabled(%r) raised; defaulting to True", skill.name)
                skill.enabled = True
        elif enabled_names is not None:
            skill.enabled = skill.name in enabled_names
        else:
            skill.enabled = True

    skills = list(skills_by_name.values())

    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    skills.sort(key=lambda s: s.name)
    return skills
