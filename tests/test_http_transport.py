"""Tests for the HTTP transport: FastMCP + CIMD OAuth AS + bridge routes wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.testclient import TestClient

from servicex_mcp.server import (
    _AuthorizeContextMiddleware,
    _CimdMetadataMiddleware,
    _make_http_mcp,
)


@pytest.fixture
def http_mcp():
    return _make_http_mcp(
        backend_url="https://servicex.example.com",
        resource_url="http://localhost:8000",
        read_only=False,
        cache_dir="/tmp/servicex_mcp_cache_test",
    )


@pytest.fixture
def http_app(http_mcp):
    mcp, _provider = http_mcp
    return _CimdMetadataMiddleware(
        _AuthorizeContextMiddleware(mcp.streamable_http_app())
    )


@pytest.fixture
def http_client(http_app):
    return TestClient(http_app, raise_server_exceptions=True)


async def _put_pending_session(provider, session_id: str) -> None:
    client_info = OAuthClientInformationFull(
        client_id="mcp-client-abc",
        redirect_uris=[AnyUrl("http://localhost:1234/callback")],
    )
    auth_params = AuthorizationParams(
        state="oauth-state",
        scopes=["openid"],
        code_challenge="challenge-abc",
        redirect_uri=AnyUrl("http://localhost:1234/callback"),
        redirect_uri_provided_explicitly=True,
    )
    url = await provider.authorize(client_info, auth_params)
    real_session_id = url.split("session=")[1]
    session = provider.store.get_by_session_id(real_session_id)
    assert session is not None
    session.session_id = session_id
    provider.store.put(session)


class TestOAuthMetadata:
    def test_authorization_server_metadata_reachable(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    def test_authorization_server_metadata_advertises_cimd(
        self, http_client: TestClient
    ) -> None:
        # Claude selects CIMD only when the AS metadata advertises both
        # client_id_metadata_document_supported and "none" in
        # token_endpoint_auth_methods_supported (public client, PKCE-only).
        data = http_client.get("/.well-known/oauth-authorization-server").json()
        assert data.get("client_id_metadata_document_supported") is True
        assert "none" in data.get("token_endpoint_auth_methods_supported", [])

    def test_authorization_server_metadata_has_no_registration_endpoint(
        self, http_client: TestClient
    ) -> None:
        # DCR is disabled — no /register endpoint is advertised.
        data = http_client.get("/.well-known/oauth-authorization-server").json()
        assert "registration_endpoint" not in data


class TestUnauthenticatedAccess:
    def test_mcp_post_without_auth_returns_401(self, http_client: TestClient) -> None:
        resp = http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401

    def test_401_response_has_www_authenticate_header(
        self, http_client: TestClient
    ) -> None:
        resp = http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert "WWW-Authenticate" in resp.headers


class TestBridgeRouteRegistered:
    async def test_get_bridge_with_valid_session_returns_200(
        self, http_mcp, http_app
    ) -> None:
        _mcp, provider = http_mcp
        await _put_pending_session(provider, "abc")
        client = TestClient(http_app, raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        assert resp.status_code == 200


class TestAuthorizeContextMiddlewareCimdLoopbackPorts:
    """Regression test for Task 14's mandatory _AuthorizeContextMiddleware wiring.

    ServiceXBridgeProvider._resolve_cimd()'s call to
    cimd.client_with_requested_redirect(cached, _authorize_redirect_uri.get())
    always receives None without this middleware, so a native MCP client's
    ephemeral-loopback-port redirect_uri never validates against its CIMD
    document's port-less declared redirect — every /authorize (not just a
    second attempt) then fails with "Redirect URI ... not registered".
    """

    def test_two_different_loopback_ports_both_succeed(
        self, http_client: TestClient
    ) -> None:
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        with patch(
            "servicex_mcp.auth.bridge_provider.resolve_cimd_client",
            AsyncMock(return_value=resolved),
        ):
            for port in (54321, 55985):
                resp = http_client.get(
                    "/authorize",
                    params={
                        "client_id": cimd_id,
                        "response_type": "code",
                        "redirect_uri": f"http://localhost:{port}/callback",
                        "code_challenge": "x" * 43,
                        "code_challenge_method": "S256",
                        "resource": "http://localhost:8000",
                    },
                    follow_redirects=False,
                )
                assert resp.status_code == 302
                assert "/bridge?session=" in resp.headers["location"]
