"""SkillsMiddleware — inject the enabled-skill list into the system prompt.

This middleware runs in :meth:`AgentMiddleware.wrap_model_call` and
appends a compact ``<available_skills>`` block to the system
message. The block lists each enabled skill by name and description
so the model knows what skills it can load with the
``read_skill`` tool.

Why a middleware?
-----------------
The backend injects the same block inside a prompt template
function (``get_skills_prompt_section``). The SDK re-implements
it as a middleware so the injection is **opt-in and
testable in isolation** — projects that do not want skills in
the system prompt simply omit the middleware from the chain.

Re-loading
----------
The middleware caches its prompt section on the first call.
Callers that mutate the on-disk skills directory mid-run can
call :meth:`invalidate_cache` to force a re-load.

Uses :meth:`wrap_model_call` so it composes into the single
``model`` graph node instead of creating a separate
``before_model`` node — saving 1 recursion_limit step per
iteration.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from agent_sdk.skills.loader import load_skills

logger = logging.getLogger(__name__)


class SkillsMiddleware(AgentMiddleware):
    """Inject the ``<available_skills>`` block into the system prompt.

    Args:
        skills_path: Filesystem path to the skills root.
        allowed_names: Optional whitelist — if supplied, only
            skills whose name is in the set are listed. Skills
            outside the whitelist are silently dropped (not
            marked ``disabled``, just omitted from the prompt).
    """

    def __init__(
        self,
        *,
        skills_path,
        allowed_names: Sequence[str] | None = None,
    ) -> None:
        super().__init__()
        from pathlib import Path  # local import — avoid a top-level heavy stdlib import

        self._skills_path = Path(skills_path)
        self._allowed_names = set(allowed_names) if allowed_names is not None else None
        self._cached_prompt: str | None = None
        self._cache_mtime: float | None = None

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def invalidate_cache(self) -> None:
        """Force the next :meth:`wrap_model_call` to re-read skills from disk."""
        self._cached_prompt = None
        self._cache_mtime = None

    def _skills_dir_mtime(self) -> float:
        """Return the most recent mtime of the skills directory tree."""
        import os as _os

        try:
            return _os.path.getmtime(self._skills_path)
        except OSError:
            return 0.0

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(self) -> str:
        skills = load_skills(self._skills_path, enabled_only=True)
        if self._allowed_names is not None:
            skills = [s for s in skills if s.name in self._allowed_names]
        if not skills:
            return ""

        items = "\n".join(
            f"- {skill.name}: {skill.description} — read with `read_skill('{skill.name}')`"
            for skill in skills
        )
        return (
            "<available_skills>\n"
            "You have access to skills that provide optimized workflows for specific tasks. "
            "Each skill contains best practices, frameworks, and references to additional resources.\n"
            f"{items}\n"
            "</available_skills>\n\n"
            "<skill_usage>\n"
            "- Load the main definition: `read_skill('<name>')`\n"
            "- Load a supporting file (scripts, references, templates, workflows): "
            "`read_skill('<name>', file='path/to/resource.md')`\n"
            "- Browse a subdirectory within a skill: "
            "`read_skill('<name>', file='subdir/')` — returns the directory listing\n"
            "- **Never** use `ls`, `glob`, `grep`, or `read_file` to explore or access skill "
            "content.  `read_skill` reads directly from the host — it is the ONLY tool that "
            "can access skill files.  Filesystem tools cannot see the skills directory.\n"
            "- Load referenced resources only when needed during execution; "
            "do not pre-load the entire skill tree.\n"
            "</skill_usage>\n\n"
            "Use the `read_skill` tool to load a skill's full SKILL.md before tackling complex "
            "tasks that match one of the available skills. Do not guess a workflow when a skill "
            "is available — load the skill first."
        )

    def _get_prompt(self) -> str:
        # Auto-invalidate when the on-disk skills directory has changed
        # (new / removed / modified skill).  Manual invalidate_cache() is
        # still available for callers that mutate skills in-process.
        current_mtime = self._skills_dir_mtime()
        if self._cache_mtime is not None and current_mtime != self._cache_mtime:
            self.invalidate_cache()
        if self._cached_prompt is not None:
            return self._cached_prompt
        self._cached_prompt = self._build_prompt()
        self._cache_mtime = current_mtime
        return self._cached_prompt

    # ------------------------------------------------------------------
    # wrap_model_call
    # ------------------------------------------------------------------

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        prompt = self._get_prompt()
        if not prompt:
            return handler(request)

        # Build the new system message with the skills block appended.
        current_system = request.system_message
        if current_system is not None and current_system.content:
            content = current_system.content
            if isinstance(content, str) and prompt.strip() in content:
                # Already present — no-op.
                return handler(request)
            new_content = f"{content}\n\n{prompt}" if isinstance(content, str) else f"{prompt}"
        else:
            new_content = prompt

        return handler(request.override(system_message=SystemMessage(content=new_content)))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        prompt = self._get_prompt()
        if not prompt:
            return await handler(request)

        current_system = request.system_message
        if current_system is not None and current_system.content:
            content = current_system.content
            if isinstance(content, str) and prompt.strip() in content:
                return await handler(request)
            new_content = f"{content}\n\n{prompt}" if isinstance(content, str) else f"{prompt}"
        else:
            new_content = prompt

        return await handler(request.override(system_message=SystemMessage(content=new_content)))