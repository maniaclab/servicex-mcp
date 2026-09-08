"""Tests for ServiceXClientFactory, EnvBasedClientFactory, and BearerTokenClientFactory."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from servicex_mcp.auth.factory import (
    BearerTokenClientFactory,
    EnvBasedClientFactory,
    ServiceXClientFactory,
    _cache_key,
    _extract_request_auth,
    build_http_servicex_client,
)
from servicex_mcp.auth.session_cache import SessionCache


def test_factory_is_abstract() -> None:
    with pytest.raises(TypeError):
        ServiceXClientFactory()  # type: ignore[abstract]


class TestEnvBasedClientFactory:
    def test_get_client_returns_stored_client(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(MagicMock()) is client

    def test_get_client_ignores_ctx(self) -> None:
        client = MagicMock()
        factory = EnvBasedClientFactory(client=client)
        assert factory.get_client(None) is client

    def test_close_is_noop(self) -> None:
        factory = EnvBasedClientFactory(client=MagicMock())
        factory.close()  # must not raise


def test_build_http_servicex_client_does_not_require_config_file(
    tmp_path, monkeypatch
) -> None:
    # No .servicex file anywhere near tmp_path or $HOME in this test env.
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    client = build_http_servicex_client(
        url="https://servicex.example.com", refresh_token="tok", cache_dir=str(tmp_path)
    )
    try:
        assert client.servicex.url == "https://servicex.example.com"
        assert client.servicex.refresh_token == "tok"
    finally:
        client.query_cache.close()


def test_build_http_servicex_client_creates_fresh_query_cache_per_client(
    tmp_path,
) -> None:
    # Two clients built for different callers must not share query cache state.
    client1 = build_http_servicex_client(
        url="https://servicex.example.com",
        refresh_token="tok-1",
        cache_dir=str(tmp_path),
    )
    client2 = build_http_servicex_client(
        url="https://servicex.example.com",
        refresh_token="tok-2",
        cache_dir=str(tmp_path),
    )
    try:
        assert client1.query_cache is not client2.query_cache
    finally:
        client1.query_cache.close()
        client2.query_cache.close()


class TestExtractRequestAuth:
    def _make_ctx(self, bearer: str, session_id: str = "sess-1") -> MagicMock:
        ctx = MagicMock()
        headers: dict[str, str] = {
            "authorization": f"Bearer {bearer}",
            "mcp-session-id": session_id,
        }
        ctx.request_context.request.headers.get.side_effect = headers.get
        return ctx

    def test_extracts_session_id_and_bearer(self) -> None:
        ctx = self._make_ctx("servicex-refresh-tok", session_id="my-session")
        session_id, bearer = _extract_request_auth(ctx)
        assert session_id == "my-session"
        assert bearer == "servicex-refresh-tok"

    def test_missing_bearer_raises_permission_error(self) -> None:
        ctx = MagicMock()
        ctx.request_context.request.headers.get.side_effect = {
            "mcp-session-id": "s"
        }.get
        with pytest.raises(PermissionError, match="Bearer"):
            _extract_request_auth(ctx)

    def test_malformed_authorization_header_raises_permission_error(self) -> None:
        ctx = MagicMock()
        headers = {"authorization": "Basic abc123", "mcp-session-id": "s"}
        ctx.request_context.request.headers.get.side_effect = headers.get
        with pytest.raises(PermissionError, match="Bearer"):
            _extract_request_auth(ctx)


def test_cache_key_does_not_contain_raw_bearer() -> None:
    bearer = "super-secret-refresh-token"
    key = _cache_key("sess-1", bearer)
    assert bearer not in key
    assert key.startswith("sess-1:")


class TestBearerTokenClientFactory:
    def _make_ctx(self, bearer: str, session_id: str = "sess-1") -> MagicMock:
        ctx = MagicMock()
        headers: dict[str, str] = {
            "authorization": f"Bearer {bearer}",
            "mcp-session-id": session_id,
        }
        ctx.request_context.request.headers.get.side_effect = headers.get
        return ctx

    def test_get_client_builds_http_client(self) -> None:
        ctx = self._make_ctx("servicex-refresh-tok")
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        sentinel = MagicMock()
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            return_value=sentinel,
        ) as mock_build:
            client = factory.get_client(ctx)
        assert client is sentinel
        mock_build.assert_called_once_with(
            url="https://servicex.example.com",
            refresh_token="servicex-refresh-tok",
            cache_dir="/tmp/cache",
        )

    def test_get_client_returns_cached_client_on_second_call(self) -> None:
        ctx = self._make_ctx("servicex-refresh-tok", session_id="fixed-session")
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            side_effect=lambda **_kw: MagicMock(),
        ):
            first = factory.get_client(ctx)
            second = factory.get_client(ctx)
        assert first is second

    def test_get_client_uses_fixed_ttl(self) -> None:
        ctx = self._make_ctx("servicex-refresh-tok", session_id="ttl-session")
        cache = MagicMock(spec=SessionCache)
        cache.get.return_value = None
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        before = time.time()
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            return_value=MagicMock(),
        ):
            factory.get_client(ctx)
        _, call_args, _ = cache.put.mock_calls[0]
        expires_at = call_args[2]
        assert before + 290 < expires_at < before + 310

    def test_close_delegates_to_cache(self) -> None:
        cache = MagicMock(spec=SessionCache)
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        factory.close()
        cache.close.assert_called_once()

    def test_same_session_different_bearer_not_cached(self) -> None:
        """A stale session id with a different bearer must not reuse the old client."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        ctx1 = self._make_ctx("real-token", session_id="fixed-session")
        ctx2 = self._make_ctx("garbage", session_id="fixed-session")
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            side_effect=lambda **_kw: MagicMock(),
        ):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is not second

    def test_same_session_same_bearer_hits_cache(self) -> None:
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        ctx1 = self._make_ctx("real-token", session_id="fixed-session")
        ctx2 = self._make_ctx("real-token", session_id="fixed-session")
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            side_effect=lambda **_kw: MagicMock(),
        ):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is second

    def test_reauth_with_fresh_bearer_rebuilds_client(self) -> None:
        """A client that re-authenticates mid-session must not keep the stale token."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        ctx_old = self._make_ctx("old-token", session_id="fixed-session")
        ctx_new = self._make_ctx("new-token", session_id="fixed-session")
        captured: list[dict[str, object]] = []

        def fake_build(**kw: object) -> MagicMock:
            captured.append(dict(kw))
            return MagicMock()

        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            side_effect=fake_build,
        ):
            factory.get_client(ctx_old)
            factory.get_client(ctx_new)
        assert captured[0]["refresh_token"] == "old-token"
        assert captured[1]["refresh_token"] == "new-token"

    def test_missing_session_id_skips_cache(self) -> None:
        """Empty mcp-session-id must never be cached (no cross-tenant sharing)."""
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        ctx1 = self._make_ctx("tok", session_id="")
        ctx2 = self._make_ctx("tok", session_id="")
        with patch(
            "servicex_mcp.auth.factory.build_http_servicex_client",
            side_effect=lambda **_kw: MagicMock(),
        ):
            first = factory.get_client(ctx1)
            second = factory.get_client(ctx2)
        assert first is not second
        assert cache.size() == 0

    def test_missing_bearer_raises_permission_error(self) -> None:
        cache = SessionCache()
        factory = BearerTokenClientFactory(
            cache=cache,
            backend_url="https://servicex.example.com",
            cache_dir="/tmp/cache",
        )
        ctx = MagicMock()
        ctx.request_context.request.headers.get.side_effect = {
            "mcp-session-id": "s"
        }.get
        with pytest.raises(PermissionError, match="Bearer"):
            factory.get_client(ctx)
