"""Tests for /bridge GET+POST routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from servicex_mcp.auth.bridge_provider import ServiceXBridgeProvider
from servicex_mcp.auth.bridge_routes import make_bridge_handlers


def _make_provider() -> ServiceXBridgeProvider:
    return ServiceXBridgeProvider(
        resource_url="http://localhost:8000",
        backend_url="https://servicex.example.com",
    )


def _make_app(provider: ServiceXBridgeProvider) -> Starlette:
    bridge_get, bridge_post = make_bridge_handlers(provider)
    return Starlette(
        routes=[
            Route("/bridge", bridge_get, methods=["GET"]),
            Route("/bridge", bridge_post, methods=["POST"]),
        ]
    )


async def _put_pending_session(
    provider: ServiceXBridgeProvider, session_id: str
) -> None:
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
    # Re-key the session under the caller's requested session_id so tests can
    # pick an easy-to-assert-on ID rather than the random one authorize() mints.
    session = provider.store.get_by_session_id(real_session_id)
    assert session is not None
    session.session_id = session_id
    provider.store.put(session)


class TestBridgeGet:
    def test_missing_session_param_returns_400(self) -> None:
        provider = _make_provider()
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.get("/bridge")
        assert resp.status_code == 400

    def test_unknown_session_returns_404(self) -> None:
        provider = _make_provider()
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.get("/bridge?session=nonexistent")
        assert resp.status_code == 404

    async def test_valid_session_returns_html_form_with_session_id(self) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.get("/bridge?session=abc")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "abc" in resp.text


class TestBridgePost:
    def test_missing_session_param_returns_400(self) -> None:
        provider = _make_provider()
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge", data={"token": "tok"})
        assert resp.status_code == 400

    def test_unknown_session_returns_404(self) -> None:
        provider = _make_provider()
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=nonexistent", data={"token": "tok"})
        assert resp.status_code == 404

    async def test_missing_token_field_returns_400_with_form(self) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")
        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=abc", data={})
        assert resp.status_code == 400
        assert "form" in resp.text.lower() or "<form" in resp.text

    async def test_valid_token_redirects_to_redirect_uri_with_code(self) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")

        async def _fake_submit_token(session_id: str, token: str) -> None:
            provider.store.mark_done(
                session_id, servicex_token=token, auth_code="mcp-code-xyz"
            )

        provider.submit_token = AsyncMock(side_effect=_fake_submit_token)  # type: ignore[method-assign]

        client = TestClient(
            _make_app(provider), raise_server_exceptions=True, follow_redirects=False
        )
        resp = client.post("/bridge?session=abc", data={"token": "pasted-token"})
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("http://localhost:1234/callback?")
        assert "code=mcp-code-xyz" in location
        assert "state=oauth-state" in location

    async def test_invalid_token_returns_400_and_rerenders_form_with_error(
        self,
    ) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")

        async def _fake_submit_token(_session_id: str, _token: str) -> None:
            msg = "invalid refresh token"
            raise ValueError(msg)

        provider.submit_token = AsyncMock(side_effect=_fake_submit_token)  # type: ignore[method-assign]

        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=abc", data={"token": "bad-token"})
        assert resp.status_code == 400
        assert "<form" in resp.text
        assert (
            "invalid refresh token" in resp.text.lower()
            or "invalid token" in resp.text.lower()
        )
