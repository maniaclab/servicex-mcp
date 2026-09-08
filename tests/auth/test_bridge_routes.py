"""Tests for /bridge GET+POST routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from servicex_mcp.auth.bridge_provider import ServiceXBridgeProvider
from servicex_mcp.auth.bridge_routes import _build_form_html, make_bridge_handlers

if TYPE_CHECKING:
    from starlette.responses import Response


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

    async def test_resubmitting_a_completed_session_is_rejected(self) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")
        provider.store.mark_done(
            "abc", servicex_token="already-submitted", auth_code="mcp-code-xyz"
        )
        submit_token = AsyncMock()
        provider.submit_token = submit_token  # type: ignore[method-assign]

        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=abc", data={"token": "second-token"})
        assert resp.status_code == 400
        # A second, different token must never overwrite the first
        # token/auth_code pair on an already-completed session.
        submit_token.assert_not_called()

    async def test_expired_between_mark_done_and_lookup_returns_graceful_400(
        self,
    ) -> None:
        provider = _make_provider()
        await _put_pending_session(provider, "abc")

        async def _fake_submit_token(session_id: str, token: str) -> None:
            provider.store.mark_done(
                session_id, servicex_token=token, auth_code="mcp-code-xyz"
            )
            # Simulate the session's fixed TTL lapsing between mark_done and
            # the handler's follow-up lookup.
            session = provider.store.get_by_session_id(session_id)
            assert session is not None
            session.expires_at = 0.0

        provider.submit_token = AsyncMock(side_effect=_fake_submit_token)  # type: ignore[method-assign]

        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=abc", data={"token": "pasted-token"})
        assert resp.status_code == 400
        assert "expired" in resp.text.lower()

    async def test_non_string_token_field_is_not_treated_as_a_token(self) -> None:
        # A multipart submission can put a file (UploadFile, not a str) under
        # the "token" field name; only a real string counts as a submitted
        # token. Exercised directly against the handler (rather than via
        # TestClient's real multipart encoding) to isolate the isinstance
        # guard from unrelated SpooledTemporaryFile GC-timing noise.
        provider = _make_provider()
        await _put_pending_session(provider, "abc")
        submit_token = AsyncMock()
        provider.submit_token = submit_token  # type: ignore[method-assign]
        _bridge_get, bridge_post = make_bridge_handlers(provider)

        request = MagicMock()
        request.query_params.get.return_value = "abc"
        request.form = AsyncMock(return_value={"token": MagicMock(name="UploadFile")})

        resp: Response = await bridge_post(request)  # type: ignore[misc]
        assert resp.status_code == 400
        assert "required" in bytes(resp.body).decode().lower()
        submit_token.assert_not_called()

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

    async def test_error_message_is_html_escaped_in_rerendered_form(self) -> None:
        # A future exception type (or a compromised ServiceX backend) could
        # echo attacker-influenced content into the error message — the
        # error text must never be interpolated into the page unescaped.
        provider = _make_provider()
        await _put_pending_session(provider, "abc")

        async def _fake_submit_token(_session_id: str, _token: str) -> None:
            msg = "<script>alert(1)</script>"
            raise ValueError(msg)

        provider.submit_token = AsyncMock(side_effect=_fake_submit_token)  # type: ignore[method-assign]

        client = TestClient(_make_app(provider), raise_server_exceptions=True)
        resp = client.post("/bridge?session=abc", data={"token": "bad-token"})
        assert resp.status_code == 400
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text
        assert (
            "invalid refresh token" in resp.text.lower()
            or "invalid token" in resp.text.lower()
        )


class TestBuildFormHtml:
    def test_session_id_is_html_escaped(self) -> None:
        # session_id can never actually contain markup in production (it's a
        # secrets.token_urlsafe(32) output), but the escape must not silently
        # regress if that scheme ever changes.
        html_out = _build_form_html(session_id="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html_out
        assert "&lt;script&gt;" in html_out
