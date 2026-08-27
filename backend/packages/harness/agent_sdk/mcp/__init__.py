"""MCP (Model Context Protocol) subsystem for agent runtime.

This package is a re-implementation (per ADR-010) of
``deerflow.mcp``. The SDK exposes:

Config types
------------
* :class:`McpServerConfig` / :class:`McpServersConfig` —
  Pydantic config types
* :class:`McpOAuthConfig` — OAuth token configuration

Client
------
* :func:`build_servers_config` / :func:`build_server_params` —
  pure functions that translate SDK config into
  ``langchain-mcp-adapters`` parameters

Tools
-----
* :func:`get_mcp_tools` — async function that loads LangChain
  tools from enabled MCP servers
* :func:`list_mcp_tool_names` — inspect server names (no I/O)

OAuth (5.5.9)
-------------
* :class:`OAuthTokenManager` — acquire/cache/refresh OAuth
  tokens for HTTP/SSE MCP servers
* :func:`build_oauth_tool_interceptor` — build an interceptor
  that injects ``Authorization`` headers per tool call
* :func:`get_initial_oauth_headers` — resolve initial headers
  for MCP connections

The ``langchain-mcp-adapters`` package is an **optional
extra**; when it is not installed, :func:`get_mcp_tools`
returns an empty list and logs a warning.
"""

from __future__ import annotations

from agent_sdk.mcp.client import build_server_params, build_servers_config
from agent_sdk.mcp.config import McpOAuthConfig, McpServerConfig, McpServersConfig, config_from_extensions_dict
from agent_sdk.mcp.oauth import OAuthTokenManager, build_oauth_tool_interceptor, get_initial_oauth_headers
from agent_sdk.mcp.tools import get_mcp_tools, list_mcp_tool_names

__all__ = [
    "McpOAuthConfig",
    "McpServerConfig",
    "McpServersConfig",
    "OAuthTokenManager",
    "build_oauth_tool_interceptor",
    "build_server_params",
    "build_servers_config",
    "config_from_extensions_dict",
    "get_initial_oauth_headers",
    "get_mcp_tools",
    "list_mcp_tool_names",
]
