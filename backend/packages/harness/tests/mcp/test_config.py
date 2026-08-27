"""Unit tests for :mod:`agent_sdk.mcp.config`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestMcpServerConfig:
    def test_default_type_is_stdio(self) -> None:
        from agent_sdk.mcp.config import McpServerConfig

        cfg = McpServerConfig()
        assert cfg.type == "stdio"
        assert cfg.enabled is True

    def test_default_collections_are_empty(self) -> None:
        from agent_sdk.mcp.config import McpServerConfig

        cfg = McpServerConfig()
        # Empty containers (not None) so build_server_params always sees
        # the keys it expects and langchain-mcp-adapters never hits a
        # missing-key path.
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.headers == {}

    def test_stdio_command_must_be_string(self) -> None:
        # The config layer accepts ``type='stdio'`` without a command —
        # the command-requirement check happens in build_server_params.
        # We verify here that an int command is rejected at the type level.
        from agent_sdk.mcp.config import McpServerConfig

        with pytest.raises(ValidationError):
            McpServerConfig(type="stdio", command=42)  # type: ignore[arg-type]

    def test_extra_fields_are_allowed(self) -> None:
        from agent_sdk.mcp.config import McpServerConfig

        cfg = McpServerConfig(type="stdio", command="x", extra_field="ok")
        # extra='allow' means the field is preserved.
        assert cfg.model_extra == {"extra_field": "ok"}


class TestMcpServersConfig:
    def test_get_enabled_excludes_disabled(self) -> None:
        from agent_sdk.mcp.config import McpServerConfig, McpServersConfig

        cfg = McpServersConfig(
            servers={
                "a": McpServerConfig(command="x", enabled=True),
                "b": McpServerConfig(command="y", enabled=False),
            }
        )
        enabled = cfg.get_enabled()
        assert "a" in enabled
        assert "b" not in enabled

    def test_extra_fields_forbidden(self) -> None:
        from agent_sdk.mcp.config import McpServersConfig

        with pytest.raises(ValidationError):
            McpServersConfig.model_validate({"servers": {}, "rogue": True})


class TestConfigFromExtensionsDict:
    def test_loads_mcp_servers_key(self) -> None:
        from agent_sdk.mcp.config import config_from_extensions_dict

        cfg = config_from_extensions_dict(
            {
                "mcpServers": {
                    "alpha": {"type": "stdio", "command": "python"},
                    "beta": {"type": "http", "url": "https://example.com"},
                }
            }
        )
        assert set(cfg.servers.keys()) == {"alpha", "beta"}
        assert cfg.servers["alpha"].type == "stdio"
        assert cfg.servers["beta"].url == "https://example.com"

    def test_loads_snake_case_key(self) -> None:
        from agent_sdk.mcp.config import config_from_extensions_dict

        cfg = config_from_extensions_dict({"mcp_servers": {"x": {"command": "y"}}})
        assert "x" in cfg.servers

    def test_empty_or_missing_returns_empty(self) -> None:
        from agent_sdk.mcp.config import config_from_extensions_dict

        assert config_from_extensions_dict({}).servers == {}
        assert config_from_extensions_dict({"mcpServers": None}).servers == {}

    def test_non_dict_mcp_servers_raises(self) -> None:
        from agent_sdk.mcp.config import config_from_extensions_dict

        with pytest.raises(ValueError, match="mapping"):
            config_from_extensions_dict({"mcpServers": ["not a dict"]})
