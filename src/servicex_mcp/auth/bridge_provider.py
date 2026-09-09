"""ServiceXBridgeProvider — OAuthAuthorizationServerProvider for the ServiceX paste bridge.

MCP clients speak standard auth-code+PKCE and are identified via CIMD (Client ID
Metadata Documents — an https client_id URL; no DCR). This provider bridges that
to ServiceX's own personal-refresh-token model: instead of an external IdP
redirect, the user pastes their ServiceX refresh token into the ``/bridge`` page.
Unlike rucio-mcp's polling bridge, there is no external IdP to poll — the pasted
token is validated synchronously (in the same request as the ``/bridge`` POST)
against ServiceX's own ``/token/refresh`` exchange, then returned verbatim to
the MCP client as the OAuth access_token.

Flow:
  authorize()      → creates a pending BridgeSession, returns the /bridge URL
  /bridge page     → user pastes their ServiceX refresh token, POSTs the form
  submit_token()   → validates the token against ServiceX, mints a local auth_code
  /token exchange  → returns the ServiceX refresh token as access_token (passthrough)
  MCP tool calls   → bearer = ServiceX refresh token → BearerTokenClientFactory
"""

from __future__ import annotations

import base64
import contextvars
import json as _json
import logging
import secrets
import threading
import time
from collections import OrderedDict

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    IdentityAssertionParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from servicex.servicex_adapter import ServiceXAdapter

from servicex_mcp.auth.bridge_state import BridgeSession, BridgeStateStore
from servicex_mcp.auth.cimd import (
    CimdError,
    client_with_requested_redirect,
    is_cimd_client_id,
    resolve_cimd_client,
)

_log = logging.getLogger(__name__)

# Set by _AuthorizeContextMiddleware (server.py) for the duration of each
# /authorize request.  Gives _resolve_cimd() the requested redirect_uri so a
# CIMD client's ephemeral-port loopback redirect can be matched port-agnostically
# against its Client ID Metadata Document.
_authorize_redirect_uri: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_authorize_redirect_uri", default=None
)

_DEFAULT_EXPIRES_IN = 3600  # fallback when token is opaque or has no exp claim

# Bounds on the resolved-CIMD-client cache: a TTL caps staleness of rotated CIMD
# documents, and a size cap prevents an attacker filling memory with distinct
# client_id URL paths (one domain, unlimited paths).
_CIMD_CACHE_TTL = 3600.0
_CIMD_CACHE_MAX = 256


def _jwt_expires_in(token: str) -> int:
    """Return seconds until the JWT expires, or _DEFAULT_EXPIRES_IN for opaque tokens."""
    parts = token.split(".")
    if len(parts) != 3:
        return _DEFAULT_EXPIRES_IN
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        if exp is None:
            return _DEFAULT_EXPIRES_IN
        remaining = int(exp) - int(time.time())
        return max(remaining, 0)
    except Exception:  # noqa: BLE001
        return _DEFAULT_EXPIRES_IN


class ServiceXBridgeProvider:
    """Implements :class:`OAuthAuthorizationServerProvider` via ServiceX's PAT-paste flow.

    One instance per deployment; shared state is in :attr:`store` and ``_clients``.
    Validation of the pasted refresh token is synchronous (see :meth:`submit_token`)
    since there is no external IdP to poll — unlike rucio-mcp's bridge.
    """

    def __init__(
        self,
        *,
        resource_url: str,
        backend_url: str,
    ) -> None:
        """Initialize the ServiceX bridge provider.

        *resource_url* is this servicex-mcp deployment's own public URL, used
        to construct the ``/bridge?session=`` interstitial URL.  *backend_url*
        is the ServiceX deployment URL that pasted refresh tokens are
        validated against in :meth:`submit_token`.
        """
        self._resource_url = resource_url.rstrip("/")
        self._backend_url = backend_url.rstrip("/")
        self.store = BridgeStateStore()
        # client_id URL → (resolved client, expiry epoch); LRU-ordered, TTL+size
        # bounded (see _cache_get / _cache_put).
        self._clients: OrderedDict[str, tuple[OAuthClientInformationFull, float]] = (
            OrderedDict()
        )
        self._clients_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Client identity (CIMD only — no DCR)
    # ------------------------------------------------------------------

    async def register_client(self, _client_info: OAuthClientInformationFull) -> None:
        """Not supported: this server identifies clients via CIMD, not DCR.

        Dynamic Client Registration is disabled
        (``ClientRegistrationOptions(enabled=False)`` in server.py) so the SDK
        never routes a ``/register`` request here.  The provider protocol allows
        raising :class:`NotImplementedError` when DCR is unsupported.
        """
        msg = (
            "Dynamic Client Registration is not supported; use CIMD "
            "(an https client_id URL)"
        )
        raise NotImplementedError(msg)

    def _cache_get(self, client_id: str) -> OAuthClientInformationFull | None:
        """Return the cached client if present and unexpired, else ``None`` (LRU)."""
        now = time.time()
        with self._clients_lock:
            entry = self._clients.get(client_id)
            if entry is None:
                return None
            client, expires_at = entry
            if expires_at <= now:
                del self._clients[client_id]
                return None
            self._clients.move_to_end(client_id)
            return client

    def _cache_put(self, client_id: str, client: OAuthClientInformationFull) -> None:
        """Store *client* with a fresh TTL, evicting the oldest over the size cap."""
        with self._clients_lock:
            self._clients[client_id] = (client, time.time() + _CIMD_CACHE_TTL)
            self._clients.move_to_end(client_id)
            while len(self._clients) > _CIMD_CACHE_MAX:
                self._clients.popitem(last=False)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Resolve a CIMD client_id URL to its client information.

        1. In-memory cache hit (a previously-resolved CIMD client).
        2. CIMD: if ``client_id`` is an https URL, dereference it (Client ID
           Metadata Document) and cache the result.
        3. Otherwise unknown → ``None`` (the SDK emits "Client ID not found").

        The cache holds the canonical document-derived client; the requested
        redirect_uri (the ``_authorize_redirect_uri`` contextvar, set by
        ``_AuthorizeContextMiddleware`` during /authorize) is appended to a
        per-request copy so a fresh ephemeral loopback port passes the SDK's
        exact-match validation on every attempt, not just the first.
        """
        cached = self._cache_get(client_id)
        if cached is not None:
            _log.debug("get_client: hit for client_id=%s", client_id)
            return client_with_requested_redirect(cached, _authorize_redirect_uri.get())

        if is_cimd_client_id(client_id):
            return await self._resolve_cimd(client_id)

        _log.debug("get_client: miss for non-CIMD client_id=%s", client_id)
        return None

    async def _resolve_cimd(self, client_id: str) -> OAuthClientInformationFull | None:
        """Dereference a CIMD client_id URL, caching the canonical public client.

        Only the document-derived client is cached — never a per-request
        redirect_uri, which would pin the first attempt's ephemeral port for
        every later authorization.  On the /token leg the contextvar is unset,
        but the client resolved during /authorize is already cached, so no
        re-fetch is needed.
        """
        try:
            resolved = await resolve_cimd_client(client_id)
        except CimdError as exc:
            _log.warning(
                "get_client: CIMD resolution failed for client_id=%s: %s",
                client_id,
                exc,
            )
            return None
        self._cache_put(client_id, resolved)
        _log.debug("get_client: resolved CIMD client_id=%s", client_id)
        return client_with_requested_redirect(resolved, _authorize_redirect_uri.get())

    # ------------------------------------------------------------------
    # Authorization flow
    # ------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Create a pending bridge session and return the interstitial /bridge URL.

        Unlike rucio-mcp's bridge, there is no external IdP to kick off here and
        no background polling task to start — the /bridge page itself collects
        the pasted refresh token, and validation happens synchronously in
        :meth:`submit_token` once the user submits the form.
        """
        session_id = secrets.token_urlsafe(32)
        session = BridgeSession(
            session_id=session_id,
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            client_id=client.client_id or "",
            scopes=params.scopes or [],
            resource=params.resource,
            state=params.state,
            expires_at=time.time() + 300,
        )
        self.store.put(session)
        _log.info(
            "Bridge session %s started for client %s", session_id[:8], client.client_id
        )
        return f"{self._resource_url}/bridge?session={session_id}"

    async def submit_token(self, session_id: str, token: str) -> None:
        """Validate a pasted ServiceX refresh token and mark the session done.

        Called synchronously by the ``/bridge`` POST handler (bridge_routes.py):
        there is no external IdP to poll, so the whole authentication outcome
        (valid or invalid) is decided within this one request/response cycle.

        Raises :class:`ValueError` if *session_id* is unknown or has expired.
        On an invalid *token*, the session is marked ``error`` and the
        underlying exception is re-raised (not swallowed) so the route handler
        can render a specific "invalid token" error page instead of a generic
        "something went wrong" message.
        """
        session = self.store.get_by_session_id(session_id)
        if session is None:
            msg = f"Unknown or expired bridge session: {session_id}"
            raise ValueError(msg)

        # ServiceXAdapter has no public "just validate this token" method.
        # _get_authorization(force_reauth=True) is the smallest real call that
        # actually exercises the /token/refresh exchange against the pasted
        # refresh token — so it's used here deliberately, even though it's a
        # single-underscore "internal" method of the third-party `servicex`
        # package. This could break if a future servicex release renames or
        # removes it.
        adapter = ServiceXAdapter(url=self._backend_url, refresh_token=token)
        try:
            await adapter._get_authorization(force_reauth=True)  # pylint: disable=protected-access
        except Exception as exc:
            # Logged (not just recorded on the session) so a validation
            # failure caused by a future servicex release renaming/removing
            # _get_authorization is visible in server logs immediately,
            # rather than only discoverable via user reports or by
            # inspecting store.session_counts() after the fact.
            _log.warning(
                "Bridge session %s: token validation failed: %s",
                session_id[:8],
                exc,
            )
            self.store.mark_error(session_id, str(exc))
            raise

        auth_code = secrets.token_urlsafe(32)
        self.store.mark_done(session_id, servicex_token=token, auth_code=auth_code)
        _log.info("Bridge session %s: authentication complete", session_id[:8])

    async def load_authorization_code(
        self, _client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        """Return an :class:`AuthorizationCode` if *authorization_code* maps to a done session."""
        session = self.store.get_by_auth_code(authorization_code)
        if session is None or session.status != "done":
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=session.scopes,
            expires_at=session.expires_at,
            client_id=session.client_id,
            code_challenge=session.code_challenge,
            redirect_uri=session.redirect_uri,  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=session.redirect_uri_provided_explicitly,
            resource=session.resource,
        )

    async def exchange_authorization_code(
        self, _client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Return the ServiceX refresh token verbatim as the OAuth access_token.

        The session is popped atomically so the authorization code is single-use
        (OAuth 2.1): a captured/replayed ``/token`` request finds nothing.
        """
        session = self.store.pop_by_auth_code(authorization_code.code)
        if session is None or session.servicex_token is None:
            raise TokenError(
                error="invalid_grant",
                error_description="Authorization code not found or expired",
            )
        expires_in = _jwt_expires_in(session.servicex_token)
        _log.debug("exchange_authorization_code: expires_in=%ds", expires_in)
        return OAuthToken(
            access_token=session.servicex_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=None,
        )

    # ------------------------------------------------------------------
    # Access / refresh token handling
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Return a synthetic AccessToken wrapping the ServiceX refresh token.

        No signature validation is performed — the bearer IS the ServiceX
        refresh token and ServiceX will reject it with 401 if it is invalid.
        """
        _log.debug("load_access_token called, token prefix=%s…", token[:12])
        return AccessToken(
            token=token,
            client_id="servicex-bridge",
            scopes=[],
            expires_at=None,
        )

    async def load_refresh_token(
        self, _client: OAuthClientInformationFull, _refresh_token: str
    ) -> RefreshToken | None:
        """Refresh tokens are not issued in v1; always returns None."""
        return None

    async def exchange_refresh_token(
        self,
        _client: OAuthClientInformationFull,
        _refresh_token: RefreshToken,
        _scopes: list[str],
    ) -> OAuthToken:
        """Refresh tokens are not supported; always raises."""
        raise TokenError(
            error="unsupported_grant_type",
            error_description="Refresh tokens are not supported; re-authenticate",
        )

    async def exchange_identity_assertion(
        self,
        _client: OAuthClientInformationFull,
        _params: IdentityAssertionParams,
    ) -> OAuthToken:
        """Reject the SEP-990 ID-JAG/jwt-bearer grant, which is not supported.

        Required to satisfy OAuthAuthorizationServerProvider's structural
        protocol even though this provider doesn't inherit from it directly
        — without this, a future caller that type-annotates a variable as
        OAuthAuthorizationServerProvider would fail mypy's structural check.
        """
        raise TokenError(
            error="unsupported_grant_type",
            error_description="The JWT bearer grant is not supported by this authorization server",
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """No-op: ServiceX does not expose a token revocation endpoint."""
