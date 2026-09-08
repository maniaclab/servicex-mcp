"""Tests for ServiceXBridgeProvider — OAuthAuthorizationServerProvider bridge."""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from servicex.servicex_adapter import AuthorizationError

from servicex_mcp.auth import bridge_provider as _bp
from servicex_mcp.auth.bridge_provider import (
    _DEFAULT_EXPIRES_IN,
    ServiceXBridgeProvider,
    _authorize_redirect_uri,
    _jwt_expires_in,
)
from servicex_mcp.auth.bridge_state import BridgeSession
from servicex_mcp.auth.cimd import CimdError

_MODULE = "servicex_mcp.auth.bridge_provider"


@pytest.fixture
def provider() -> ServiceXBridgeProvider:
    return ServiceXBridgeProvider(
        resource_url="http://localhost:8000",
        backend_url="https://servicex.example.com",
    )


@pytest.fixture
def client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="mcp-client-abc",
        redirect_uris=[AnyUrl("http://localhost:1234/callback")],
    )


@pytest.fixture
def auth_params() -> AuthorizationParams:
    return AuthorizationParams(
        state="csrf-state",
        scopes=["openid"],
        code_challenge="challenge-abc",
        redirect_uri=AnyUrl("http://localhost:1234/callback"),
        redirect_uri_provided_explicitly=True,
    )


def _make_session(session_id: str = "sess-1", **kwargs: Any) -> BridgeSession:
    defaults: dict[str, Any] = {
        "session_id": session_id,
        "code_challenge": "challenge-abc",
        "redirect_uri": "http://localhost:1234/callback",
        "redirect_uri_provided_explicitly": True,
        "client_id": "mcp-client-abc",
        "scopes": ["openid"],
        "resource": None,
        "state": "csrf-state",
        "expires_at": time.time() + 300,
    }
    defaults.update(kwargs)
    return BridgeSession(**defaults)


def _put_pending_session(
    provider: ServiceXBridgeProvider, session_id: str = "sess-1"
) -> BridgeSession:
    session = _make_session(session_id)
    provider.store.put(session)
    return session


class TestClientRegistry:
    async def test_get_unknown_client_returns_none(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        result = await provider.get_client("nonexistent")
        assert result is None

    async def test_register_client_not_supported(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        """DCR is disabled — register_client must raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await provider.register_client(client_info)

    async def test_non_cimd_client_id_returns_none(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """An opaque (non-URL) client_id is unknown without DCR → None."""
        result = await provider.get_client("opaque-dcr-style-id")
        assert result is None

    async def test_cimd_client_id_resolved_and_cached(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """An https-URL client_id is resolved via CIMD and cached for reuse."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        with patch(
            f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)
        ) as mock_resolve:
            first = await provider.get_client(cimd_id)
            # Second lookup must hit the cache, not re-fetch the document.
            second = await provider.get_client(cimd_id)

        assert first is resolved
        assert second is resolved
        mock_resolve.assert_awaited_once()

    async def test_cimd_passes_authorize_redirect_uri(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """The /authorize redirect_uri contextvar is applied to the resolved client."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        requested = "http://localhost:51763/callback"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )
        token = _authorize_redirect_uri.set(requested)
        try:
            with patch(
                f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)
            ):
                client = await provider.get_client(cimd_id)
        finally:
            _authorize_redirect_uri.reset(token)
        assert client is not None
        client.validate_redirect_uri(AnyUrl(requested))

    async def test_cimd_resolution_failure_returns_none(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """A CimdError during resolution yields None (no client), not an exception."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        with patch(
            f"{_MODULE}.resolve_cimd_client",
            AsyncMock(side_effect=CimdError("bad document")),
        ):
            result = await provider.get_client(cimd_id)
        assert result is None

    async def test_cimd_second_authorize_with_new_ephemeral_port(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """Re-auth with a fresh loopback port must validate against the cached client.

        Claude Code binds a new ephemeral localhost port on every auth attempt
        (RFC 8252 §7.3); the client cached during the first /authorize must not
        pin the first attempt's port.  Regression test for the second-auth
        ``invalid_request: Redirect URI not registered for client``.
        """
        cimd_id = "https://claude.ai/oauth/claude-code-client-metadata"
        doc = {
            "client_id": cimd_id,
            "redirect_uris": [
                "http://localhost/callback",
                "http://127.0.0.1/callback",
            ],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
        }
        with (
            patch("servicex_mcp.auth.cimd.assert_safe_url"),
            patch(
                "servicex_mcp.auth.cimd.fetch_client_document",
                AsyncMock(return_value=doc),
            ),
        ):
            token = _authorize_redirect_uri.set("http://localhost:54321/callback")
            try:
                first = await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)
            token = _authorize_redirect_uri.set("http://localhost:55985/callback")
            try:
                second = await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)

        assert first is not None
        assert second is not None
        # The SDK's exact-match gate must accept each attempt's own port.
        first.validate_redirect_uri(AnyUrl("http://localhost:54321/callback"))
        second.validate_redirect_uri(AnyUrl("http://localhost:55985/callback"))

    async def test_cimd_cache_stores_canonical_client(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """The cached CIMD client holds only the document's declared redirect URIs.

        Per-request ephemeral ports are appended to a copy, never stored, so the
        cache neither pins the first port nor accumulates one entry per attempt.
        """
        cimd_id = "https://claude.ai/oauth/claude-code-client-metadata"
        declared = ["http://localhost/callback", "http://127.0.0.1/callback"]
        doc = {
            "client_id": cimd_id,
            "redirect_uris": declared,
            "token_endpoint_auth_method": "none",
        }
        with (
            patch("servicex_mcp.auth.cimd.assert_safe_url"),
            patch(
                "servicex_mcp.auth.cimd.fetch_client_document",
                AsyncMock(return_value=doc),
            ),
        ):
            token = _authorize_redirect_uri.set("http://localhost:54321/callback")
            try:
                await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(token)

        cached = provider._cache_get(cimd_id)
        assert cached is not None
        assert [str(u) for u in (cached.redirect_uris or [])] == declared

    async def test_token_leg_returns_cached_client_unchanged(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        """With the contextvar unset (/token leg) the cached client is returned as-is."""
        cimd_id = "https://claude.ai/.well-known/oauth-client"
        resolved = OAuthClientInformationFull(
            client_id=cimd_id,
            redirect_uris=[AnyUrl("http://localhost:1234/callback")],
            token_endpoint_auth_method="none",
        )
        with patch(f"{_MODULE}.resolve_cimd_client", AsyncMock(return_value=resolved)):
            tok = _authorize_redirect_uri.set("http://localhost:1234/callback")
            try:
                await provider.get_client(cimd_id)
            finally:
                _authorize_redirect_uri.reset(tok)
            # /token leg: no contextvar → identical cached object.
            assert await provider.get_client(cimd_id) is resolved


class TestCimdClientCache:
    """The resolved-CIMD-client cache is TTL- and size-bounded."""

    def _client(self, cid: str) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=cid,
            redirect_uris=[AnyUrl("http://localhost/callback")],
            token_endpoint_auth_method="none",
        )

    def test_expired_entry_evicted(self, provider: ServiceXBridgeProvider) -> None:
        cid = "https://claude.ai/a"
        provider._cache_put(cid, self._client(cid))
        assert provider._cache_get(cid) is not None
        # Force expiry by rewriting the stored deadline into the past.
        client, _ = provider._clients[cid]
        provider._clients[cid] = (client, time.time() - 1)
        assert provider._cache_get(cid) is None
        assert cid not in provider._clients

    def test_size_cap_evicts_oldest(
        self, provider: ServiceXBridgeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_bp, "_CIMD_CACHE_MAX", 2)
        for name in ("a", "b", "c"):
            cid = f"https://claude.ai/{name}"
            provider._cache_put(cid, self._client(cid))
        assert provider._cache_get("https://claude.ai/a") is None  # oldest evicted
        assert provider._cache_get("https://claude.ai/b") is not None
        assert provider._cache_get("https://claude.ai/c") is not None


class TestAuthorize:
    async def test_returns_bridge_url(
        self,
        provider: ServiceXBridgeProvider,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        url = await provider.authorize(client_info, auth_params)
        assert url.startswith("http://localhost:8000/bridge?session=")

    async def test_authorize_creates_pending_session(
        self,
        provider: ServiceXBridgeProvider,
        client_info: OAuthClientInformationFull,
        auth_params: AuthorizationParams,
    ) -> None:
        url = await provider.authorize(client_info, auth_params)

        session_id = url.split("session=")[1]
        session = provider.store.get_by_session_id(session_id)
        assert session is not None
        assert session.status == "pending"
        assert session.code_challenge == "challenge-abc"


class TestSubmitToken:
    async def test_submit_token_success_marks_session_done(
        self, monkeypatch: pytest.MonkeyPatch, provider: ServiceXBridgeProvider
    ) -> None:
        session = _put_pending_session(provider)
        fake_adapter = MagicMock()
        fake_adapter._get_authorization = AsyncMock(
            return_value={"Authorization": "Bearer x"}
        )
        monkeypatch.setattr(
            "servicex_mcp.auth.bridge_provider.ServiceXAdapter",
            lambda *a, **k: fake_adapter,  # noqa: ARG005
        )
        await provider.submit_token(session.session_id, "pasted-refresh-token")
        updated = provider.store.get_by_session_id(session.session_id)
        assert updated is not None
        assert updated.status == "done"
        assert updated.servicex_token == "pasted-refresh-token"

    async def test_submit_token_invalid_marks_session_error(
        self, monkeypatch: pytest.MonkeyPatch, provider: ServiceXBridgeProvider
    ) -> None:
        session = _put_pending_session(provider)
        fake_adapter = MagicMock()
        fake_adapter._get_authorization = AsyncMock(
            side_effect=AuthorizationError("nope")
        )
        monkeypatch.setattr(
            "servicex_mcp.auth.bridge_provider.ServiceXAdapter",
            lambda *a, **k: fake_adapter,  # noqa: ARG005
        )
        with pytest.raises(AuthorizationError):
            await provider.submit_token(session.session_id, "bad-token")
        updated = provider.store.get_by_session_id(session.session_id)
        assert updated is not None
        assert updated.status == "error"

    async def test_submit_token_constructs_adapter_with_backend_url(
        self, monkeypatch: pytest.MonkeyPatch, provider: ServiceXBridgeProvider
    ) -> None:
        session = _put_pending_session(provider)
        fake_adapter = MagicMock()
        fake_adapter._get_authorization = AsyncMock(return_value={})
        ctor = MagicMock(return_value=fake_adapter)
        monkeypatch.setattr("servicex_mcp.auth.bridge_provider.ServiceXAdapter", ctor)
        await provider.submit_token(session.session_id, "pasted-refresh-token")
        ctor.assert_called_once_with(
            url="https://servicex.example.com", refresh_token="pasted-refresh-token"
        )

    async def test_submit_token_unknown_session_raises_value_error(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        with pytest.raises(ValueError, match="session"):
            await provider.submit_token("ghost-session", "some-token")

    async def test_submit_token_expired_session_raises_value_error(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        session = _make_session("expired-sess", expires_at=time.time() - 1)
        provider.store.put(session)
        with pytest.raises(ValueError, match="session"):
            await provider.submit_token("expired-sess", "some-token")


class TestLoadAuthorizationCode:
    async def test_returns_none_for_unknown_code(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        result = await provider.load_authorization_code(client_info, "bad-code")
        assert result is None

    async def test_returns_none_for_pending_session(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider.store.put(session)
        provider.store.mark_done("s1", servicex_token="tok", auth_code="code-abc")
        # Manually reset to pending to simulate race
        s = provider.store.get_by_session_id("s1")
        assert s is not None
        s.status = "pending"

        result = await provider.load_authorization_code(client_info, "code-abc")
        assert result is None

    async def test_returns_authorization_code_for_done_session(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider.store.put(session)
        provider.store.mark_done("s1", servicex_token="tok", auth_code="code-abc")

        result = await provider.load_authorization_code(client_info, "code-abc")
        assert result is not None
        assert isinstance(result, AuthorizationCode)
        assert result.code == "code-abc"
        assert result.code_challenge == "challenge-abc"
        assert result.client_id == "mcp-client-abc"


class TestExchangeAuthorizationCode:
    async def test_returns_servicex_token_as_access_token(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("s1")
        provider.store.put(session)
        provider.store.mark_done(
            "s1", servicex_token="servicex-session-tok", auth_code="code-abc"
        )

        auth_code = AuthorizationCode(
            code="code-abc",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert isinstance(token, OAuthToken)
        assert token.access_token == "servicex-session-tok"
        assert token.token_type == "Bearer"
        assert token.refresh_token is None

    async def test_raises_on_missing_session(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        auth_code = AuthorizationCode(
            code="nonexistent",
            scopes=[],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        with pytest.raises(TokenError):
            await provider.exchange_authorization_code(client_info, auth_code)

    async def test_authorization_code_is_single_use(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        """OAuth 2.1: a replayed /token request with the same code must fail."""
        session = _make_session("s-once")
        provider.store.put(session)
        provider.store.mark_done(
            "s-once", servicex_token="servicex-tok", auth_code="once-code"
        )
        auth_code = AuthorizationCode(
            code="once-code",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        first = await provider.exchange_authorization_code(client_info, auth_code)
        assert first.access_token == "servicex-tok"
        # Second exchange with the captured code must be rejected.
        with pytest.raises(TokenError) as exc_info:
            await provider.exchange_authorization_code(client_info, auth_code)
        assert exc_info.value.error == "invalid_grant"


class TestLoadAccessToken:
    async def test_returns_synthetic_access_token(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        result = await provider.load_access_token("servicex-bearer-xyz")
        assert result is not None
        assert isinstance(result, AccessToken)
        assert result.token == "servicex-bearer-xyz"
        assert result.client_id == "servicex-bridge"

    async def test_no_validation_any_string_accepted(
        self, provider: ServiceXBridgeProvider
    ) -> None:
        result = await provider.load_access_token("not-a-real-token")
        assert result is not None


class TestRefreshAndRevoke:
    async def test_load_refresh_token_returns_none(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        result = await provider.load_refresh_token(client_info, "any-token")
        assert result is None

    async def test_exchange_refresh_token_raises(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        rt = RefreshToken(token="rt", client_id="c", scopes=[])
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(client_info, rt, [])

    async def test_revoke_token_is_noop(self, provider: ServiceXBridgeProvider) -> None:
        token = AccessToken(token="tok", client_id="c", scopes=[])
        await provider.revoke_token(token)  # must not raise


def _make_test_jwt(payload: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


class TestJwtExpiresIn:
    def test_future_exp_returns_remaining_seconds(self) -> None:
        future = int(time.time()) + 3600
        token = _make_test_jwt({"exp": future})
        result = _jwt_expires_in(token)
        assert 3595 <= result <= 3600

    def test_past_exp_returns_zero(self) -> None:
        past = int(time.time()) - 60
        token = _make_test_jwt({"exp": past})
        assert _jwt_expires_in(token) == 0

    def test_no_exp_claim_returns_default(self) -> None:
        token = _make_test_jwt({"sub": "alice"})
        assert _jwt_expires_in(token) == _DEFAULT_EXPIRES_IN

    def test_opaque_token_returns_default(self) -> None:
        assert _jwt_expires_in("opaque-no-dots") == _DEFAULT_EXPIRES_IN

    def test_malformed_payload_returns_default(self) -> None:
        # valid header, invalid base64 body
        assert _jwt_expires_in("header.!!!.sig") == _DEFAULT_EXPIRES_IN


class TestExchangeAuthorizationCodeExpiresIn:
    async def test_expires_in_reflects_jwt_lifetime(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        future_exp = int(time.time()) + 3600
        servicex_token = _make_test_jwt({"exp": future_exp, "sub": "alice"})

        session = _make_session("exp-s1")
        provider.store.put(session)
        provider.store.mark_done(
            "exp-s1", servicex_token=servicex_token, auth_code="exp-code"
        )

        auth_code = AuthorizationCode(
            code="exp-code",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert token.access_token == servicex_token
        assert token.expires_in is not None
        assert 3595 <= token.expires_in <= 3600

    async def test_expires_in_opaque_token_uses_default(
        self, provider: ServiceXBridgeProvider, client_info: OAuthClientInformationFull
    ) -> None:
        session = _make_session("exp-s2")
        provider.store.put(session)
        provider.store.mark_done(
            "exp-s2", servicex_token="opaque-token", auth_code="exp-code2"
        )

        auth_code = AuthorizationCode(
            code="exp-code2",
            scopes=["openid"],
            expires_at=time.time() + 300,
            client_id="mcp-client-abc",
            code_challenge="challenge-abc",
            redirect_uri=AnyUrl("http://localhost:1234/callback"),
            redirect_uri_provided_explicitly=True,
        )
        token = await provider.exchange_authorization_code(client_info, auth_code)
        assert token.expires_in == _DEFAULT_EXPIRES_IN
