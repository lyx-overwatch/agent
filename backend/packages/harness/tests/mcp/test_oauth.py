"""Unit tests for :mod:`agent_sdk.mcp.oauth`."""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ------------------------------------------------------------------
# McpOAuthConfig
# ------------------------------------------------------------------


class TestMcpOAuthConfig:
    def test_defaults(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig

        cfg = McpOAuthConfig(token_url="https://auth.example.com/token")
        assert cfg.enabled is True
        assert cfg.grant_type == "client_credentials"
        assert cfg.token_field == "access_token"
        assert cfg.token_type_field == "token_type"
        assert cfg.expires_in_field == "expires_in"
        assert cfg.default_token_type == "Bearer"
        assert cfg.refresh_skew_seconds == 60
        assert cfg.client_id is None
        assert cfg.client_secret is None
        assert cfg.scope is None
        assert cfg.audience is None
        assert cfg.extra_token_params == {}

    def test_extra_fields_allowed(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig

        cfg = McpOAuthConfig(token_url="https://example.com", custom="v")
        assert cfg.model_extra == {"custom": "v"}

    def test_field_in_mcp_server_config(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig, McpServerConfig

        oauth = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )
        cfg = McpServerConfig(type="http", url="https://example.com", oauth=oauth)
        assert cfg.oauth is oauth
        assert cfg.oauth.client_id == "id"

    def test_oauth_none_by_default(self) -> None:
        from agent_sdk.mcp.config import McpServerConfig

        cfg = McpServerConfig(command="x")
        assert cfg.oauth is None


# ------------------------------------------------------------------
# OAuthTokenManager
# ------------------------------------------------------------------


class TestOAuthTokenManager:
    @staticmethod
    def _make_oauth(**overrides):
        from agent_sdk.mcp.config import McpOAuthConfig

        defaults = {
            "token_url": "https://auth.example.com/token",
            "client_id": "test-id",
            "client_secret": "test-secret",
        }
        defaults.update(overrides)
        return McpOAuthConfig(**defaults)

    def test_init_empty(self) -> None:
        from agent_sdk.mcp.oauth import OAuthTokenManager

        mgr = OAuthTokenManager({})
        assert mgr.has_oauth_servers() is False
        assert mgr.oauth_server_names() == []

    def test_init_skips_disabled(self) -> None:
        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = self._make_oauth(enabled=False)
        mgr = OAuthTokenManager({"srv": cfg})
        assert mgr.has_oauth_servers() is False
        assert mgr.oauth_server_names() == []

    def test_init_includes_enabled(self) -> None:
        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = self._make_oauth(enabled=True)
        mgr = OAuthTokenManager({"srv": cfg})
        assert mgr.has_oauth_servers() is True
        assert mgr.oauth_server_names() == ["srv"]

    def test_from_servers_config_with_mcp_server_config(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig, McpServerConfig
        from agent_sdk.mcp.oauth import OAuthTokenManager

        oauth = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )
        servers = {
            "srv1": McpServerConfig(command="x"),
            "srv2": McpServerConfig(type="http", url="https://e.com", oauth=oauth),
        }
        mgr = OAuthTokenManager.from_servers_config(servers)
        assert mgr.has_oauth_servers() is True
        assert mgr.oauth_server_names() == ["srv2"]

    def test_from_servers_config_skips_disabled_oauth(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig, McpServerConfig
        from agent_sdk.mcp.oauth import OAuthTokenManager

        oauth = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
            enabled=False,
        )
        servers = {
            "srv": McpServerConfig(type="http", url="https://e.com", oauth=oauth),
        }
        mgr = OAuthTokenManager.from_servers_config(servers)
        assert mgr.has_oauth_servers() is False

    def test_get_authorization_header_returns_none_for_unknown_server(self) -> None:
        import asyncio

        from agent_sdk.mcp.oauth import OAuthTokenManager

        mgr = OAuthTokenManager({})

        async def _run():
            return await mgr.get_authorization_header("unknown")

        result = asyncio.run(_run())
        assert result is None

    def test_get_authorization_header_fetches_and_caches(self) -> None:
        import asyncio

        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = self._make_oauth()
        mgr = OAuthTokenManager({"srv": cfg})

        # Track how many HTTP calls are made.
        call_count = 0

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, *, data=None, **kwargs):
                nonlocal call_count
                call_count += 1
                return _FakeResponse(
                    {
                        "access_token": "tok-1",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            h1 = asyncio.run(mgr.get_authorization_header("srv"))
            h2 = asyncio.run(mgr.get_authorization_header("srv"))

        assert h1 == "Bearer tok-1"
        assert h2 == "Bearer tok-1"
        assert call_count == 1  # Second call used cache.

    def test_get_authorization_header_refreshes_when_expiring(self) -> None:
        import asyncio

        from agent_sdk.mcp.oauth import OAuthTokenManager

        # Short expiry — token will be stale immediately.
        cfg = self._make_oauth(refresh_skew_seconds=99999)
        mgr = OAuthTokenManager({"srv": cfg})

        token_ids = iter(["tok-1", "tok-2"])

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, *, data=None, **kwargs):
                return _FakeResponse(
                    {
                        "access_token": next(token_ids),
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            h1 = asyncio.run(mgr.get_authorization_header("srv"))
            h2 = asyncio.run(mgr.get_authorization_header("srv"))

        assert h1 == "Bearer tok-1"
        assert h2 == "Bearer tok-2"

    def test_missing_client_credentials_raises(self) -> None:
        import asyncio

        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = self._make_oauth(client_id=None)
        mgr = OAuthTokenManager({"srv": cfg})

        async def _run():
            await mgr.get_authorization_header("srv")

        with pytest.raises(ValueError, match="client_credentials"):
            asyncio.run(_run())

    def test_unsupported_grant_type_raises(self) -> None:
        import asyncio

        from agent_sdk.mcp.config import McpOAuthConfig
        from agent_sdk.mcp.oauth import OAuthTokenManager

        # Use model_construct to bypass Pydantic Literal validation
        # (the runtime check inside _fetch_token is the real guard).
        cfg = McpOAuthConfig.model_construct(
            token_url="https://auth.example.com/token",
            grant_type="password",
            client_id="id",
            client_secret="secret",
        )
        mgr = OAuthTokenManager({"srv": cfg})

        async def _run():
            await mgr.get_authorization_header("srv")

        with pytest.raises(ValueError, match="Unsupported OAuth grant type"):
            asyncio.run(_run())

    def test_refresh_token_grant(self) -> None:
        import asyncio

        from agent_sdk.mcp.config import McpOAuthConfig
        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            grant_type="refresh_token",
            refresh_token="rt-abc",
        )
        mgr = OAuthTokenManager({"srv": cfg})

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, *, data=None, **kwargs):
                # Verify refresh_token is sent.
                assert data.get("grant_type") == "refresh_token"
                assert data.get("refresh_token") == "rt-abc"
                return _FakeResponse(
                    {
                        "access_token": "rt-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            h = asyncio.run(mgr.get_authorization_header("srv"))
        assert h == "Bearer rt-tok"

    def test_refresh_token_missing_raises(self) -> None:
        import asyncio

        from agent_sdk.mcp.config import McpOAuthConfig
        from agent_sdk.mcp.oauth import OAuthTokenManager

        cfg = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            grant_type="refresh_token",
            refresh_token=None,
        )
        mgr = OAuthTokenManager({"srv": cfg})

        async def _run():
            await mgr.get_authorization_header("srv")

        with pytest.raises(ValueError, match="refresh_token grant"):
            asyncio.run(_run())


# ------------------------------------------------------------------
# build_oauth_tool_interceptor
# ------------------------------------------------------------------


class TestBuildOAuthToolInterceptor:
    def test_returns_none_when_no_oauth_servers(self) -> None:
        from agent_sdk.mcp.oauth import build_oauth_tool_interceptor

        interceptor = build_oauth_tool_interceptor({})
        assert interceptor is None

    def test_returns_callable_when_oauth_configured(self) -> None:
        from agent_sdk.mcp.config import McpOAuthConfig
        from agent_sdk.mcp.oauth import build_oauth_tool_interceptor

        oauth = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )
        interceptor = build_oauth_tool_interceptor({"srv": oauth})
        assert interceptor is not None
        import asyncio
        assert asyncio.iscoroutinefunction(interceptor)


# ------------------------------------------------------------------
# get_initial_oauth_headers
# ------------------------------------------------------------------


class TestGetInitialOAuthHeaders:
    def test_returns_empty_when_no_oauth_servers(self) -> None:
        import asyncio

        from agent_sdk.mcp.oauth import get_initial_oauth_headers

        result = asyncio.run(get_initial_oauth_headers({}))
        assert result == {}

    def test_returns_headers_for_configured_servers(self) -> None:
        import asyncio

        from agent_sdk.mcp.config import McpOAuthConfig
        from agent_sdk.mcp.oauth import get_initial_oauth_headers

        oauth = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, *, data=None, **kwargs):
                return _FakeResponse(
                    {
                        "access_token": "init-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                )

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            result = asyncio.run(get_initial_oauth_headers({"srv": oauth}))
        assert result == {"srv": "Bearer init-tok"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class _FakeResponse:
    """Minimal fake httpx.Response for _fetch_token."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass
