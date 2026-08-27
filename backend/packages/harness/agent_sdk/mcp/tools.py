"""Load MCP tools at runtime — bridge to langchain-mcp-adapters.

This module is a re-implementation (per ADR-010) of
``deerflow.mcp.tools.get_mcp_tools``. The function imports
``langchain_mcp_adapters`` lazily so the SDK's base install
does not need it; when the optional package is not installed,
the loader returns ``[]`` and logs a warning.

What is *not* in the SDK version
---------------------------------
The in-tree reference also handles:

* OAuth header injection per request;
* custom ``mcpInterceptors`` (class-path resolvable callables);
* a process-wide thread pool for sync wrappers of async tools.

Those are scheduled for the 5.x follow-up batches because
they couple tightly to the auth subsystem and the global
event-loop policy of the host application. The SDK version
covers the common case: build a ``MultiServerMCPClient``,
return the tools, done.
"""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Any

from langchain_core.tools import BaseTool

from agent_sdk.mcp.client import build_servers_config
from agent_sdk.mcp.config import McpServersConfig

logger = logging.getLogger(__name__)


async def get_mcp_tools(servers: McpServersConfig) -> list[BaseTool]:
    """Load the tools exposed by *servers*.

    Args:
        servers: The MCP server config to instantiate.

    Returns:
        A list of LangChain tools (empty if the
        ``langchain-mcp-adapters`` extra is not installed, or
        if no servers are enabled, or if loading fails).

    Tools from servers whose ``tool_timeout`` is set are
    wrapped with an ``asyncio.wait_for`` guard so a single
    stuck tool call cannot hang the entire agent.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning(
            "langchain-mcp-adapters not installed. Install it to enable MCP tools: "
            "uv add langchain-mcp-adapters"
        )
        return []

    servers_config = build_servers_config(servers)
    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return []

    try:
        client = MultiServerMCPClient(servers_config, tool_name_prefix=True)
        tools: list[BaseTool] = await client.get_tools()
        logger.info("Successfully loaded %d MCP tool(s)", len(tools))
    except Exception:
        logger.exception("Failed to load MCP tools")
        return []

    # ── Apply per-server timeout wrappers ──────────────────────────────
    timeout_by_server: dict[str, float] = {}
    for name, cfg in servers.get_enabled().items():
        if cfg.tool_timeout is not None and cfg.tool_timeout > 0:
            timeout_by_server[name] = cfg.tool_timeout

    if timeout_by_server:
        tools = [_wrap_tool_with_timeout(t, timeout_by_server) for t in tools]

    return tools


def list_mcp_tool_names(servers: McpServersConfig) -> list[str]:
    """Return the configured server names — useful for diagnostics.

    Does not actually connect to the servers; only inspects
    the configuration. The list excludes disabled servers.
    """
    return list(servers.get_enabled().keys())


# ── Timeout wrapper ──────────────────────────────────────────────────────


def _wrap_tool_with_timeout(tool: BaseTool, timeout_by_server: dict[str, float]) -> BaseTool:
    """Wrap *tool* with ``asyncio.wait_for`` if its server has a timeout.

    The server name is parsed from the tool name prefix:
    ``"playwright_playwright_navigate"`` → server ``"playwright"``.

    When *timeout_by_server* does not contain a key for the
    server, the tool is returned unchanged.
    """
    # ── Resolve server name from tool name prefix ───────────────────────
    tool_name = getattr(tool, "name", "") or ""
    if not tool_name or "_" not in tool_name:
        return tool

    server_name, _, _remainder = tool_name.partition("_")
    timeout = timeout_by_server.get(server_name)
    if timeout is None:
        return tool

    original_invoke = tool.ainvoke

    @wraps(original_invoke)
    async def _ainvoke_with_timeout(input: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.wait_for(
                original_invoke(input, *args, **kwargs),
                timeout=timeout,
            )
        except TimeoutError:
            tool_msg = (
                f"MCP tool '{tool_name}' timed out after {timeout:.0f}s. "
                "The remote server is unresponsive. Check the server status "
                "or increase 'tool_timeout' in the MCP config."
            )
            logger.error(tool_msg)
            return tool_msg

    object.__setattr__(tool, "ainvoke", _ainvoke_with_timeout)

    logger.debug(
        "Wrapped MCP tool '%s' with %.0fs timeout (server: %s)",
        tool_name, timeout, server_name,
    )
    return tool


__all__: list[Any] = ["get_mcp_tools", "list_mcp_tool_names"]
