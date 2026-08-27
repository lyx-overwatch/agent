"""Tool loader — load tools by class path, deduplicate, and group.

This module is a re-implementation (per ADR-010) of
``deerflow.tools.tools.get_available_tools``.  It is the
brand-neutral entry point for assembling the tool list passed
to :func:`agent_sdk.create_agent`.

The loader knows nothing about DeerFlow's specific tool
catalogue, MCP servers, or skill-registration plumbing.
Products build their own
:class:`ToolConfig` records (see
:mod:`agent_sdk.presets.deerflow.tools` for the DeerFlow
preset) and pass them here.  The SDK does the boring part —
class-path resolution, deduplication, optional builtin
inclusion, and group filtering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration data class
# ---------------------------------------------------------------------------


class ToolConfig(BaseModel):
    """Declarative description of a tool to load.

    Attributes:
        name: Stable identifier (e.g. ``"bash"``).  Must
            match the loaded tool's ``.name``; a mismatch is
            logged as a WARNING because it is the root cause
            of agent-time ``not a valid tool`` errors.
        use: Class path of the tool implementation
            (e.g. ``"deerflow.sandbox.tools:bash_tool"``).
        group: Optional group tag, used for filtering
            (e.g. ``"bash"``, ``"web"``).
    """

    name: str
    use: str
    group: str | None = None


@dataclass
class LoadResult:
    """Result of a :func:`load_tools` call.

    Attributes:
        tools: Final tool list, in load order.  Order is:
            config tools first, then user-supplied builtin
            tools, then extra tools.  Duplicates are removed
            (first occurrence wins).
        skipped_duplicates: Names of tools that were dropped
            because they duplicated an earlier entry.
        mismatched_names: Pairs of ``(config_name, tool_name)``
            that diverged.  The runtime logs a WARNING for
            each.
    """

    tools: list[BaseTool] = field(default_factory=list)
    skipped_duplicates: list[str] = field(default_factory=list)
    mismatched_names: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_one(config: ToolConfig) -> BaseTool:
    """Resolve a single :class:`ToolConfig` to a :class:`BaseTool` instance."""
    from agent_sdk.reflection import resolve_class

    cls = resolve_class(config.use, base_class=BaseTool)
    return cls()


def load_tools(
    configs: list[ToolConfig] | None = None,
    *,
    builtin_tools: list[BaseTool] | None = None,
    extra_tools: list[BaseTool] | None = None,
    groups: list[str] | None = None,
) -> LoadResult:
    """Load tools from class paths and return a deduplicated list.

    Args:
        configs: Tools to load by class path.  Each entry is
            resolved via :func:`agent_sdk.reflection.resolve_class`.
        builtin_tools: Optional list of already-constructed
            tools to append after the config tools
            (e.g. an in-process ask-clarification tool).
        extra_tools: Optional list of tools appended last
            (e.g. MCP tools loaded out of band).
        groups: Optional whitelist.  When provided, only
            config tools whose ``group`` is in the list are
            loaded.

    Returns:
        A :class:`LoadResult` containing the final tool list
        plus diagnostics (duplicate names that were skipped,
        config/name mismatches that should be reviewed).

    Notes:
        The order of the returned list is: filtered config
        tools, then ``builtin_tools``, then ``extra_tools``.
        Duplicates are dropped (first occurrence wins), and
        any second-occurrence tool name is recorded in
        ``skipped_duplicates``.

        Names are compared with strict equality; a tool
        whose ``.name`` does not match its config ``name`` is
        still loaded (the tool's own ``.name`` is what
        langchain uses to bind tool calls) but the mismatch
        is recorded in ``mismatched_names`` and logged as a
        WARNING.
    """
    result = LoadResult()
    seen: set[str] = set()
    raw_configs = list(configs or [])

    # --- 1. Filter by group (if requested) ---------------------------------
    if groups is not None:
        wanted = set(groups)
        raw_configs = [c for c in raw_configs if c.group in wanted]

    # --- 2. Resolve config tools by class path -----------------------------
    for cfg in raw_configs:
        try:
            tool = _load_one(cfg)
        except ImportError as exc:
            logger.error("Failed to load tool %r (use=%s): %s", cfg.name, cfg.use, exc)
            raise
        if cfg.name != tool.name:
            logger.warning(
                "Tool name mismatch: config name %r does not match tool .name %r (use: %s). The tool's own .name will be used for binding.",
                cfg.name,
                tool.name,
                cfg.use,
            )
            result.mismatched_names.append((cfg.name, tool.name))
        if tool.name in seen:
            result.skipped_duplicates.append(tool.name)
            logger.warning(
                "Duplicate tool name %r detected in config; skipping (use only one declaration).",
                tool.name,
            )
            continue
        seen.add(tool.name)
        result.tools.append(tool)

    # --- 3. Append builtin tools (in caller-supplied order) ----------------
    for tool in builtin_tools or []:
        if tool.name in seen:
            result.skipped_duplicates.append(tool.name)
            logger.warning("Duplicate tool name %r (from builtin_tools); skipping.", tool.name)
            continue
        seen.add(tool.name)
        result.tools.append(tool)

    # --- 4. Append extra tools (MCP / etc.) --------------------------------
    for tool in extra_tools or []:
        if tool.name in seen:
            result.skipped_duplicates.append(tool.name)
            logger.warning("Duplicate tool name %r (from extra_tools); skipping.", tool.name)
            continue
        seen.add(tool.name)
        result.tools.append(tool)

    return result


__all__ = ["LoadResult", "ToolConfig", "load_tools"]
