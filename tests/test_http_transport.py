"""Tests for the HTTP transport: FastMCP + CIMD OAuth AS + bridge routes wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.testclient import TestClient

from servicex_mcp.server import (
    _AuthorizeContextMiddleware,
    _CimdMetadataMiddleware,
    _make_http_mcp,
    _transport_security_from_resource_url,
    serve_http,
)

_RESOURCE_URL = "http://localhost:8000"


@pytest.fixture
def http_mcp():
    return _make_http_mcp(
        backend_url="https://servicex.example.com",
        resource_url=_RESOURCE_URL,
        read_only=False,
        cache_dir="/tmp/servicex_mcp_cache_test",
    )


@pytest.fixture
def http_app(http_mcp):
    mcp, _provider = http_mcp
    # transport_security is passed explicitly here, matching serve_http's
    # real production wiring in server.py — the resource_url used by this
    # fixture happens to be loopback, which the SDK would auto-protect
    # anyway; TestNonLoopbackTransportSecurity below uses a public
    # resource_url specifically to exercise the case that auto-detection
    # cannot cover, since it only ever sees the *bind* host, not the
    # public resource_url clients actually connect through.
    http_app = mcp.streamable_http_app(
        transport_security=_transport_security_from_resource_url(_RESOURCE_URL)
    )
    return _CimdMetadataMiddleware(_AuthorizeContextMiddleware(http_app))


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


class TestNonLoopbackTransportSecurity:
    """Regression test for a real deployment (non-loopback resource_url).

    mcp's streamable_http_app(host=...) only auto-enables DNS-rebinding
    protection (with a 127.0.0.1/localhost/::1-only allow-list) when the
    *bind* host it's given is loopback — it has no way to know the public
    resource_url clients actually connect through. Never passing an
    explicit host= there means this auto-enable branch would silently
    never fire for a real deployment, and without an explicit
    transport_security, TransportSecurityMiddleware falls back to
    protection disabled entirely — a request against a real public
    resource_url would then either always 421 (if the bind host happened
    to still be loopback while resource_url wasn't) or accept any Host
    header at all (if a non-loopback bind host was passed to
    streamable_http_app, silently downgrading security). Building
    transport_security explicitly from resource_url avoids both failure
    modes for both local and hosted deployments.
    """

    @pytest.fixture
    def public_http_client(self):
        resource_url = "https://servicex-mcp.example.org"
        mcp, _provider = _make_http_mcp(
            backend_url="https://servicex.example.com",
            resource_url=resource_url,
            read_only=False,
            cache_dir="/tmp/servicex_mcp_cache_test",
        )
        http_app = mcp.streamable_http_app(
            transport_security=_transport_security_from_resource_url(resource_url)
        )
        app = _CimdMetadataMiddleware(_AuthorizeContextMiddleware(http_app))
        # Used as a context manager: the streamable-http session manager's
        # request handling needs its ASGI lifespan (task group) started,
        # which only happens on __enter__/__aenter__, not on bare
        # construction — a request that reaches past the auth layer without
        # this raises "Task group is not initialized" instead of exercising
        # the behavior under test.
        with TestClient(
            app, base_url=resource_url, raise_server_exceptions=True
        ) as client:
            yield client

    def test_matching_public_host_is_not_rejected(
        self, public_http_client: TestClient
    ) -> None:
        resp = public_http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Accept": "application/json, text/event-stream"},
        )
        # No Authorization header, so this must still 401 — the point of
        # this test is that it's a 401 (reached real auth handling), not a
        # 421 (rejected before auth even ran because the Host header,
        # correctly matching the public resource_url, wasn't allow-listed).
        assert resp.status_code == 401

    def test_mismatched_host_header_is_rejected(
        self, public_http_client: TestClient
    ) -> None:
        # The Host check lives deeper in the stack than the bearer-auth
        # check (an unauthenticated request 401s before ever reaching it —
        # see test_matching_public_host_is_not_rejected), so a request
        # needs *some* Authorization header to reach it at all.
        # ServiceXBridgeProvider.load_access_token is a passthrough (no
        # signature verification — the real ServiceX backend is what
        # ultimately rejects a bad token), so any bearer string is
        # sufficient to get past the auth layer for this test's purpose.
        #
        # httpx derives the Host header from the request URL itself (a
        # manually-set "Host" header in `headers=` is not what
        # TransportSecurityMiddleware sees), so hitting the same in-process
        # ASGI app through a different URL is what actually exercises a
        # mismatched Host — this is the ASGI-transport equivalent of a
        # DNS-rebinding request landing on this server under a different name.
        resp = public_http_client.post(
            "http://evil.example.net/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer some-refresh-token",
            },
        )
        # Proves the allow-list is actually active, not wide open: a
        # request claiming a different host must still be rejected even
        # though it lands on the same running server and carries what the
        # MCP auth layer accepts as a well-formed bearer.
        assert resp.status_code == 421


class TestHttpLifespanCleanup:
    async def test_factory_close_runs_on_shutdown(self) -> None:
        mcp, _provider = _make_http_mcp(
            backend_url="https://servicex.example.com",
            resource_url=_RESOURCE_URL,
            read_only=False,
            cache_dir="/tmp/servicex_mcp_cache_test",
        )
        app = mcp.streamable_http_app(
            transport_security=_transport_security_from_resource_url(_RESOURCE_URL)
        )
        with (
            patch(
                "servicex_mcp.auth.factory.BearerTokenClientFactory.close",
                autospec=True,
            ) as mock_close,
            TestClient(app),
        ):
            pass
        mock_close.assert_called_once()


class TestServeHttp:
    def test_forwards_host_port_and_log_level_to_uvicorn(self) -> None:
        with patch("servicex_mcp.server.uvicorn.run") as mock_run:
            serve_http(
                backend_url="https://servicex.example.com",
                resource_url="https://servicex-mcp.example.org",
                host="0.0.0.0",
                port=9000,
                read_only=False,
                cache_dir="/tmp/servicex_mcp_cache_test",
                log_level="debug",
            )
        mock_run.assert_called_once()
        _app_arg, kwargs = mock_run.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9000
        assert kwargs["log_level"] == "debug"

    def test_default_log_level_is_info(self) -> None:
        with patch("servicex_mcp.server.uvicorn.run") as mock_run:
            serve_http(
                backend_url="https://servicex.example.com",
                resource_url="https://servicex-mcp.example.org",
                host="127.0.0.1",
                port=8000,
                read_only=False,
                cache_dir="/tmp/servicex_mcp_cache_test",
            )
        _app_arg, kwargs = mock_run.call_args
        assert kwargs["log_level"] == "info"

    def test_builds_app_with_transport_security_matching_resource_url(self) -> None:
        # Regression guard: serve_http must derive transport_security from
        # the real resource_url and pass it to streamable_http_app, not
        # rely on the SDK's loopback-only auto-detection (which only ever
        # sees the *bind* host, never the public resource_url).
        fake_mcp = MagicMock()
        fake_provider = MagicMock()
        with (
            patch(
                "servicex_mcp.server._make_http_mcp",
                return_value=(fake_mcp, fake_provider),
            ),
            patch("servicex_mcp.server.uvicorn.run"),
        ):
            serve_http(
                backend_url="https://servicex.example.com",
                resource_url="https://servicex-mcp.example.org",
                host="0.0.0.0",
                port=8000,
                read_only=False,
                cache_dir="/tmp/servicex_mcp_cache_test",
            )
        fake_mcp.streamable_http_app.assert_called_once()
        _args, kwargs = fake_mcp.streamable_http_app.call_args
        security = kwargs["transport_security"]
        assert security.allowed_hosts == ["servicex-mcp.example.org"]
        assert security.allowed_origins == ["https://servicex-mcp.example.org"]
        assert security.enable_dns_rebinding_protection is True
