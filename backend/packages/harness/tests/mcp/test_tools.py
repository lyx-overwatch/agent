"""Unit tests for :mod:`agent_sdk.mcp.tools`."""

from __future__ import annotations

import asyncio

from agent_sdk.mcp.config import McpServerConfig, McpServersConfig


class TestListMcpToolNames:
    def test_returns_only_enabled_names(self) -> None:
        from agent_sdk.mcp.tools import list_mcp_tool_names

        cfg = McpServersConfig(
            servers={
                "a": McpServerConfig(command="x", enabled=True),
                "b": McpServerConfig(command="y", enabled=False),
            }
        )
        assert list_mcp_tool_names(cfg) == ["a"]


class TestGetMcpToolsEmpty:
    def test_no_servers_returns_empty(self) -> None:
        from agent_sdk.mcp.config import McpServersConfig
        from agent_sdk.mcp.tools import get_mcp_tools

        # No servers at all → early return, no import attempt.
        result = asyncio.run(get_mcp_tools(McpServersConfig()))
        assert result == []

