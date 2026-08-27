"""Unit tests for :mod:`agent_sdk.mcp.client` (pure server-params builder)."""

from __future__ import annotations

import pytest
from agent_sdk.mcp.config import McpServerConfig, McpServersConfig


class TestBuildServerParams:
    def test_stdio(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        cfg = McpServerConfig(type="stdio", command="python", args=["-m", "srv"], env={"X": "1"})
        params = build_server_params("alpha", cfg)
        assert params == {"transport": "stdio", "command": "python", "args": ["-m", "srv"], "env": {"X": "1"}}

    def test_stdio_defaults_to_stdio(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        cfg = McpServerConfig(command="python")  # no type
        params = build_server_params("alpha", cfg)
        assert params["transport"] == "stdio"

    def test_stdio_missing_command_raises(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        with pytest.raises(ValueError, match="command"):
            build_server_params("alpha", McpServerConfig(type="stdio"))

    def test_sse(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        cfg = McpServerConfig(type="sse", url="https://example.com/sse", headers={"X-Auth": "tok"})
        params = build_server_params("alpha", cfg)
        assert params == {
            "transport": "sse",
            "url": "https://example.com/sse",
            "headers": {"X-Auth": "tok"},
        }

    def test_http(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        cfg = McpServerConfig(type="http", url="https://example.com/mcp")
        params = build_server_params("alpha", cfg)
        assert params["transport"] == "http"
        assert params["url"] == "https://example.com/mcp"

    def test_http_missing_url_raises(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        with pytest.raises(ValueError, match="url"):
            build_server_params("alpha", McpServerConfig(type="http"))

    def test_unsupported_transport_raises(self) -> None:
        from agent_sdk.mcp.client import build_server_params

        # model_construct bypasses Pydantic validation so we can reach
        # the runtime ValueError inside build_server_params.
        cfg = McpServerConfig.model_construct(type="grpc", command="x")
        with pytest.raises(ValueError, match="unsupported"):
            build_server_params("alpha", cfg)


class TestBuildServersConfig:
    def test_skips_disabled(self) -> None:
        from agent_sdk.mcp.client import build_servers_config

        cfg = McpServersConfig(
            servers={
                "on": McpServerConfig(command="python", enabled=True),
                "off": McpServerConfig(command="python", enabled=False),
            }
        )
        out = build_servers_config(cfg)
        assert "on" in out
        assert "off" not in out

    def test_skips_misconfigured(self) -> None:
        from agent_sdk.mcp.client import build_servers_config

        cfg = McpServersConfig(
            servers={
                "good": McpServerConfig(command="python"),
                "bad": McpServerConfig(type="stdio"),  # missing command
            }
        )
        out = build_servers_config(cfg)
        assert "good" in out
        assert "bad" not in out
