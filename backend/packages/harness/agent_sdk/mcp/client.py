"""MCP client — translate SDK config into langchain-mcp-adapters parameters.

This module is a re-implementation (per ADR-010) of
``deerflow.mcp.client``. The SDK version is **pure**
(no I/O, no global state) — given a :class:`McpServersConfig`
it returns the parameter dict that
``langchain_mcp_adapters.client.MultiServerMCPClient`` expects.
A separate function loads the actual tools (see
:mod:`agent_sdk.mcp.tools`).
"""

from __future__ import annotations

from typing import Any

from agent_sdk.mcp.config import McpServerConfig, McpServersConfig


def build_server_params(server_name: str, config: McpServerConfig) -> dict[str, Any]:
    """Build the parameter dict for one MCP server.

    Args:
        server_name: The server's name (used in error messages).
        config: The server's configuration.

    Returns:
        A dict suitable for
        ``MultiServerMCPClient({name: params})``.

    Raises:
        ValueError: If the config is missing the required
            fields for its declared transport type, or the
            transport type is unsupported.
    """
    transport_type = config.type or "stdio"
    params: dict[str, Any] = {"transport": transport_type}

    if transport_type == "stdio":
        if not config.command:
            raise ValueError(f"MCP server '{server_name}' with stdio transport requires 'command' field")
        params["command"] = config.command
        # Always set 'args' — backend convention. langchain-mcp-adapters
        # expects a list (possibly empty) for the stdio transport.
        params["args"] = list(config.args)
        if config.env:
            params["env"] = dict(config.env)
    elif transport_type in ("sse", "http", "streamable_http", "streamable-http"):
        if not config.url:
            raise ValueError(f"MCP server '{server_name}' with {transport_type} transport requires 'url' field")
        params["url"] = config.url
        if config.headers:
            params["headers"] = dict(config.headers)
    else:
        raise ValueError(f"MCP server '{server_name}' has unsupported transport type: {transport_type}")

    return params


def build_servers_config(servers: McpServersConfig) -> dict[str, dict[str, Any]]:
    """Build the parameter dict for every enabled MCP server.

    Servers whose :func:`build_server_params` raises are
    skipped with a logged warning (the agent still starts,
    just without the offending server's tools).
    """
    import logging

    logger = logging.getLogger(__name__)

    out: dict[str, dict[str, Any]] = {}
    for name, cfg in servers.get_enabled().items():
        try:
            out[name] = build_server_params(name, cfg)
        except Exception as exc:
            logger.error("Failed to configure MCP server '%s': %s", name, exc)
    return out
