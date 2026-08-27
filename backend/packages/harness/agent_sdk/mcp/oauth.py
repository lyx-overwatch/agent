"""OAuth token support for MCP HTTP/SSE servers.

This module is a re-implementation (per ADR-010) of
``deerflow.mcp.oauth``. The SDK version is **standalone** —
it takes a plain ``dict[str, McpOAuthConfig]`` instead of
an ``ExtensionsConfig`` container, so a project can wire it
into any configuration scheme it likes.

Public surface
--------------
* :class:`OAuthTokenManager` — acquire/cache/refresh OAuth tokens
* :func:`build_oauth_tool_interceptor` — build a tool interceptor
  that injects ``Authorization`` headers per request
* :func:`get_initial_oauth_headers` — resolve initial headers for
  MCP server connections

All functions are pure async — no global state or config
singletons.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_sdk.mcp.config import McpOAuthConfig

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


@dataclass
class _OAuthToken:
    """Cached OAuth token."""

    access_token: str
    token_type: str
    expires_at: datetime


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers.

    Args:
        oauth_by_server: Mapping of server name →
            :class:`McpOAuthConfig`. Only servers whose
            ``oauth.enabled=True`` will be managed; others are
            silently skipped.
    """

    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]) -> None:
        self._oauth_by_server = {
            name: cfg
            for name, cfg in oauth_by_server.items()
            if cfg.enabled
        }
        self._tokens: dict[str, _OAuthToken] = {}
        self._locks: dict[str, asyncio.Lock] = {
            name: asyncio.Lock() for name in self._oauth_by_server
        }

    @classmethod
    def from_servers_config(
        cls, servers: dict[str, Any]
    ) -> OAuthTokenManager:
        """Build a token manager from a mapping of server configs.

        Each value in *servers* may be an :class:`McpOAuthConfig`
        or a :class:`McpServerConfig` (whose ``.oauth`` field is
        inspected). Servers without OAuth config are silently
        skipped.
        """
        oauth_by_server: dict[str, McpOAuthConfig] = {}
        for name, cfg in servers.items():
            oauth = getattr(cfg, "oauth", None)
            if oauth is not None:
                if isinstance(oauth, McpOAuthConfig) and oauth.enabled:
                    oauth_by_server[name] = oauth
        return cls(oauth_by_server)

    # -- queries ---------------------------------------------------

    def has_oauth_servers(self) -> bool:
        """Return ``True`` when at least one server has OAuth enabled."""
        return bool(self._oauth_by_server)

    def oauth_server_names(self) -> list[str]:
        """Return the names of servers with OAuth enabled."""
        return list(self._oauth_by_server.keys())

    # -- token lifecycle -------------------------------------------

    async def get_authorization_header(self, server_name: str) -> str | None:
        """Return the ``Authorization`` header value for *server_name*.

        On first call (or when the cached token is expiring) this
        fetches a fresh token from the OAuth endpoint.  Subsequent
        calls reuse the cached token until it approaches expiry.

        Returns ``None`` when *server_name* has no OAuth config.
        """
        oauth = self._oauth_by_server.get(server_name)
        if not oauth:
            return None

        token = self._tokens.get(server_name)
        if token and not _is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"

        lock = self._locks[server_name]
        async with lock:
            # Double-check after acquiring the lock — another
            # caller may have refreshed while we were waiting.
            token = self._tokens.get(server_name)
            if token and not _is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"

            fresh = await _fetch_token(oauth)
            self._tokens[server_name] = fresh
            logger.info(
                "Refreshed OAuth access token for MCP server: %s",
                server_name,
            )
            return f"{fresh.token_type} {fresh.access_token}"


# ------------------------------------------------------------------
# Interceptor factory
# ------------------------------------------------------------------


def build_oauth_tool_interceptor(
    oauth_by_server: dict[str, McpOAuthConfig],
) -> Any | None:
    """Build a tool interceptor that injects OAuth ``Authorization`` headers.

    Args:
        oauth_by_server: Mapping of server name →
            :class:`McpOAuthConfig`.

    Returns:
        An async callable ``(request, handler)`` suitable for use
        as an MCP tool interceptor, or ``None`` if no servers have
        OAuth enabled.
    """
    token_manager = OAuthTokenManager(oauth_by_server)
    if not token_manager.has_oauth_servers():
        return None

    async def _oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await token_manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)

        updated_headers = dict(request.headers or {})
        updated_headers["Authorization"] = header
        return await handler(request.override(headers=updated_headers))

    return _oauth_interceptor


# ------------------------------------------------------------------
# Initial headers
# ------------------------------------------------------------------


async def get_initial_oauth_headers(
    oauth_by_server: dict[str, McpOAuthConfig],
) -> dict[str, str]:
    """Get initial OAuth ``Authorization`` headers for MCP connections.

    Args:
        oauth_by_server: Mapping of server name →
            :class:`McpOAuthConfig`.

    Returns:
        Mapping of ``{server_name: "Bearer <token>"}`` for every
        server whose token was successfully fetched.
    """
    token_manager = OAuthTokenManager(oauth_by_server)
    if not token_manager.has_oauth_servers():
        return {}

    headers: dict[str, str] = {}
    for server_name in token_manager.oauth_server_names():
        value = await token_manager.get_authorization_header(server_name)
        if value:
            headers[server_name] = value

    return headers


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _is_expiring(token: _OAuthToken, oauth: McpOAuthConfig) -> bool:
    """Return True when *token* will expire within the configured skew window."""
    now = datetime.now(UTC)
    skew = max(oauth.refresh_skew_seconds, 0)
    return token.expires_at <= now + timedelta(seconds=skew)


async def _fetch_token(oauth: McpOAuthConfig) -> _OAuthToken:
    """POST to the token endpoint and return a cached :class:`_OAuthToken`."""
    import httpx  # pyright: ignore[reportMissingImports]

    data: dict[str, str] = {
        "grant_type": oauth.grant_type,
        **oauth.extra_token_params,
    }

    if oauth.scope:
        data["scope"] = oauth.scope
    if oauth.audience:
        data["audience"] = oauth.audience

    if oauth.grant_type == "client_credentials":
        if not oauth.client_id or not oauth.client_secret:
            raise ValueError(
                "OAuth client_credentials requires client_id and client_secret"
            )
        data["client_id"] = oauth.client_id
        data["client_secret"] = oauth.client_secret
    elif oauth.grant_type == "refresh_token":
        if not oauth.refresh_token:
            raise ValueError(
                "OAuth refresh_token grant requires refresh_token"
            )
        data["refresh_token"] = oauth.refresh_token
        if oauth.client_id:
            data["client_id"] = oauth.client_id
        if oauth.client_secret:
            data["client_secret"] = oauth.client_secret
    else:
        raise ValueError(
            f"Unsupported OAuth grant type: {oauth.grant_type}"
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(oauth.token_url, data=data)
        response.raise_for_status()
        payload = response.json()

    access_token = payload.get(oauth.token_field)
    if not access_token:
        raise ValueError(
            f"OAuth token response missing '{oauth.token_field}'"
        )

    token_type = str(
        payload.get(oauth.token_type_field, oauth.default_token_type)
        or oauth.default_token_type
    )

    expires_in_raw = payload.get(oauth.expires_in_field, 3600)
    try:
        expires_in = int(expires_in_raw)
    except (TypeError, ValueError):
        expires_in = 3600

    expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in, 1))
    return _OAuthToken(
        access_token=access_token,
        token_type=token_type,
        expires_at=expires_at,
    )


__all__: list[Any] = [
    "OAuthTokenManager",
    "build_oauth_tool_interceptor",
    "get_initial_oauth_headers",
]
