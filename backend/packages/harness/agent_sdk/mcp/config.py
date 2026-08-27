"""MCP server configuration data classes (Pydantic).

This module is a re-implementation (per ADR-010) of the MCP
config types in ``deerflow.config.extensions_config``. The
in-tree config is a single ``ExtensionsConfig`` Pydantic
model that also carries skills and channels; the SDK splits
it so the MCP-only types live in their own module. A
``McpServersConfig`` can be constructed standalone or merged
into a project-specific extensions config.

Compatibility notes
-------------------
* ``type`` is a plain ``str`` (default ``"stdio"``) — not a
  ``Literal`` — so projects that adopt a newer transport
  (e.g. ``"streamable-http"``) do not hit a Pydantic
  ``ValidationError`` at config-load time. Unknown
  transport values are caught later by
  :func:`agent_sdk.mcp.client.build_server_params`, which
  raises a clear :class:`ValueError`.
* ``args`` / ``env`` / ``headers`` default to **empty
  containers** (matching the in-tree reference). This
  keeps ``build_server_params`` output consistent — the
  ``args`` key is always present on ``stdio`` params, so
  the downstream ``langchain-mcp-adapters`` client never
  sees a missing key.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpOAuthConfig(BaseModel):
    """OAuth configuration for an MCP server (HTTP/SSE transports).

    This is a re-implementation (per ADR-010) of
    ``deerflow.config.extensions_config.McpOAuthConfig``.
    The SDK version is a standalone Pydantic model — it is
    not coupled to an ``ExtensionsConfig`` container. Callers
    pass instances directly to :class:`OAuthTokenManager`.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth grant type",
    )
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token (for refresh_token grant)")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience (provider-specific)")
    token_field: str = Field(default="access_token", description="Field name containing access token in token response")
    token_type_field: str = Field(default="token_type", description="Field name containing token type in token response")
    expires_in_field: str = Field(default="expires_in", description="Field name containing expiry (seconds) in token response")
    default_token_type: str = Field(default="Bearer", description="Default token type when missing in token response")
    refresh_skew_seconds: int = Field(default=60, description="Refresh token this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Attributes:
        type: Transport type. ``stdio`` launches the
            ``command`` as a child process; ``sse`` and
            ``http`` connect to a remote endpoint. Defaults
            to ``"stdio"``.
        command: Required for ``stdio`` transports.
        args: Command-line arguments for ``stdio`` (default
            empty list).
        env: Environment variables for ``stdio`` (default
            empty dict).
        url: Required for ``sse`` / ``http`` transports.
        headers: HTTP headers (e.g. ``Authorization``;
            default empty dict).
        enabled: Whether this server should be loaded. The
            loader skips disabled servers silently.
        oauth: Optional OAuth configuration for token-based
            authentication (HTTP/SSE transports only).
    """

    model_config = ConfigDict(extra="allow")

    type: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    tool_timeout: float | None = Field(default=None, description="Per-tool-call timeout in seconds. None means no timeout.")
    oauth: McpOAuthConfig | None = None


class McpServersConfig(BaseModel):
    """A bag of MCP server configs, keyed by name.

    The key in the ``servers`` dict is the server name —
    the agent runtime uses it as the tool name prefix.
    """

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    def get_enabled(self) -> dict[str, McpServerConfig]:
        """Return the subset of servers whose ``enabled=True``."""
        return {name: cfg for name, cfg in self.servers.items() if cfg.enabled}


def config_from_extensions_dict(data: dict[str, Any]) -> McpServersConfig:
    """Build an :class:`McpServersConfig` from a raw extensions dict.

    The convention matches the in-tree reference: the
    extensions config has a top-level ``mcpServers`` key
    whose value is a mapping of name → server-config-dict.
    """
    raw = data.get("mcpServers", data.get("mcp_servers", {})) or {}
    if not isinstance(raw, dict):
        raise ValueError("mcpServers must be a mapping of name → config")
    return McpServersConfig(servers={name: McpServerConfig(**cfg) for name, cfg in raw.items() if isinstance(cfg, dict)})
