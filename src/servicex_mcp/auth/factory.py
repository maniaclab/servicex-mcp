"""ServiceX client factory: abstracts how the ServiceXClient is obtained per-request."""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

from servicex.configuration import Configuration
from servicex.query_cache import QueryCache
from servicex.servicex_adapter import ServiceXAdapter
from servicex.servicex_client import ServiceXClient

if TYPE_CHECKING:
    from servicex_mcp.auth.session_cache import SessionCache


class _RedeemedAccessToken(Protocol):
    """Structural shape of a redeemed ServiceX access token.

    A read-only property, not a plain attribute: a plain ``access_token:
    str`` annotation would require write access too (PEP 544's default for
    protocol attributes), which af-credentials' actual ``ServiceXAccessToken``
    -- a frozen dataclass -- cannot satisfy.
    """

    @property
    def access_token(self) -> str: ...


class ServiceXRedeemer(Protocol):
    """Redeems a ServiceX access token from the AF MCP broker for a given bearer.

    Matches ``af_credentials.proxy.ProxyClient``'s ``kind="servicex"``
    support (maniaclab/af-credentials#9, shipped in af-credentials v0.3.1)
    via structural typing rather than a hard import: ``ProxyClient(broker_url,
    kind="servicex")`` satisfies this protocol directly, but the one concrete
    construction site lives in ``server.py``, keeping this module's tests
    independent of af-credentials being installed at all.
    """

    async def access_token(self, bearer: str) -> _RedeemedAccessToken:
        """Redeem *bearer* (an AF Broker Identity Token) for a ServiceX access token."""


class ServiceXClientFactory(ABC):
    """Returns the ServiceXClient appropriate for the current request/session."""

    @abstractmethod
    def get_client(self, ctx: Any) -> ServiceXClient:
        """Return the ServiceXClient for the given request context."""

    @abstractmethod
    def close(self) -> None:
        """Release any cached clients or resources."""


class EnvBasedClientFactory(ServiceXClientFactory):
    """Stdio-mode factory: wraps a single ServiceXClient built at startup."""

    def __init__(self, client: ServiceXClient) -> None:
        """Store the pre-built client."""
        self._client = client

    def get_client(self, _ctx: Any) -> ServiceXClient:
        """Return the single shared client regardless of context."""
        return self._client

    def close(self) -> None:
        """No-op: stdio client holds no per-request resources to release."""


def build_http_servicex_client(
    *, url: str, refresh_token: str, cache_dir: str
) -> ServiceXClient:
    """Build a ServiceXClient from a URL + bearer token, no config file required.

    ServiceXClient.__init__ unconditionally calls Configuration.read(), which
    raises if no .servicex/servicex.yaml exists on disk. HTTP mode serves
    many callers with different tokens against one known backend URL and
    must not depend on a server-side config file, so this constructs the
    Configuration object directly instead of reading one from disk.

    This bypasses ServiceXClient.__init__ entirely (via object.__new__) and
    hand-sets the same five attributes __init__ would have — verified
    against every ServiceXClient method this project's tools call. A future
    servicex release adding a new attribute those methods start depending
    on would surface as an AttributeError at call time, not here; re-check
    this against ServiceXClient.__init__ on any servicex version bump.

    Each call opens its own on-disk QueryCache (a real file handle) —
    callers that cache the returned client (see BearerTokenClientFactory)
    are responsible for closing client.query_cache on eviction; SessionCache
    does this. A client that's never cached (no session id) relies on
    CPython's refcounting GC to close it once the caller's reference to it
    goes out of scope.
    """
    client = object.__new__(ServiceXClient)
    config = Configuration(api_endpoints=[], cache_path=cache_dir)
    client.config = config
    client.endpoints = {}
    client.servicex = ServiceXAdapter(url, refresh_token=refresh_token)
    client.query_cache = QueryCache(config)
    client._code_generators = None  # pylint: disable=protected-access
    return client


class _BrokerServiceXAdapter(ServiceXAdapter):  # type: ignore[misc]
    """A ServiceXAdapter that redeems its access token from the AF MCP broker instead of exchanging a ServiceX refresh token via ServiceX's own /token/refresh.

    ``# type: ignore[misc]`` above: ``servicex`` ships no type stubs
    (``ignore_missing_imports`` for ``servicex.*`` in ``pyproject.toml``),
    so mypy sees ``ServiceXAdapter`` as ``Any`` and flags subclassing it —
    a real constraint of this codebase's typing setup, not specific to this
    class.

    Only ``_get_token`` is overridden — ``_get_authorization``'s existing
    JWT-expiry-aware fast path (serve ``self.token`` while its own ``exp``
    claim leaves more than 60s, else re-authenticate) is untouched, so this
    adapter re-redeems exactly as often as the stock refresh-token path
    would re-call ``/token/refresh``: lazily, on first real use and
    whenever the cached access token is about to expire.

    ``bearer`` (the caller's AF Broker Identity Token) is stored in the
    base class's ``refresh_token`` slot. That is deliberate, not an
    oversight: ``_get_authorization``'s ``if not bearer_token and not
    self.refresh_token: return {}`` guard needs *something* truthy there to
    ever attempt authentication at all, and this is the only value this
    adapter has to offer it. The base class's own ``_get_token`` (which
    would POST that value to ServiceX's ``/token/refresh``) is never
    reached — it is fully replaced below.
    """

    def __init__(self, url: str, *, redeemer: ServiceXRedeemer, bearer: str) -> None:
        """Construct against *url*, redeeming *bearer* via *redeemer* on demand."""
        super().__init__(url, refresh_token=bearer)
        self._redeemer = redeemer

    async def _get_token(self) -> None:
        """Redeem the stored bearer via the broker and store the resulting access token."""
        token = await self._redeemer.access_token(self.refresh_token)
        self.token = token.access_token


def build_broker_servicex_client(
    *, url: str, redeemer: ServiceXRedeemer, bearer: str, cache_dir: str
) -> ServiceXClient:
    """Build a ServiceXClient whose adapter redeems its access token from the AF MCP broker.

    Mirrors ``build_http_servicex_client``'s ``object.__new__`` construction
    exactly, substituting ``_BrokerServiceXAdapter`` for the plain
    ``ServiceXAdapter`` — see that function's docstring for why this
    bypasses ``ServiceXClient.__init__`` entirely, and re-check both against
    ``ServiceXClient.__init__`` on any ``servicex`` version bump.
    """
    client = object.__new__(ServiceXClient)
    config = Configuration(api_endpoints=[], cache_path=cache_dir)
    client.config = config
    client.endpoints = {}
    client.servicex = _BrokerServiceXAdapter(url, redeemer=redeemer, bearer=bearer)
    client.query_cache = QueryCache(config)
    client._code_generators = None  # pylint: disable=protected-access
    return client


def _extract_request_auth(ctx: Any) -> tuple[str, str]:
    """Extract (session_id, bearer_token) from the request."""
    req = ctx.request_context.request
    session_id: str = req.headers.get("mcp-session-id", "")
    auth: str = req.headers.get("authorization", "") or ""
    if not auth.lower().startswith("bearer "):
        msg = "Missing Bearer token in Authorization header"
        raise PermissionError(msg)
    bearer = auth[7:].strip()
    return session_id, bearer


def _cache_key(session_id: str, bearer: str) -> str:
    """Bind a cache entry to both the session id and the bearer it was built for.

    A bare session id is a routing identifier that leaks into logs/proxies;
    hashing the bearer into the key prevents it from acting as a credential.
    """
    bearer_hash = hashlib.sha256(bearer.encode()).hexdigest()[:16]
    return f"{session_id}:{bearer_hash}"


class BearerTokenClientFactory(ServiceXClientFactory):
    """HTTP-mode factory: builds and caches one ServiceXClient per MCP session.

    Backend-URL-bound: one factory per ServiceX deployment. The bearer token
    (the caller's ServiceX personal refresh token) is extracted per-request
    and used to build a client whose adapter exchanges it for a short-lived
    access token via ServiceX's own /token/refresh, lazily on first use.
    """

    def __init__(
        self, *, cache: SessionCache, backend_url: str, cache_dir: str
    ) -> None:
        """Store the session cache, backend URL, and download cache directory."""
        self._cache = cache
        self._backend_url = backend_url
        self._cache_dir = cache_dir

    def get_client(self, ctx: Any) -> ServiceXClient:
        """Return a cached or newly built ServiceXClient for this session.

        The cache key binds the session id to a hash of the bearer, so a
        stale/guessed session id paired with a different bearer never
        returns another caller's client, and a session that re-authenticates
        with a fresh bearer rebuilds rather than reusing the stale token.
        Requests without a session id (e.g. stateless mode) are never
        cached, to avoid sharing a client across unrelated callers.
        """
        session_id, bearer = _extract_request_auth(ctx)
        cache_key = _cache_key(session_id, bearer) if session_id else None
        cached = self._cache.get(cache_key) if cache_key else None
        if cached is not None:
            return cached
        client = build_http_servicex_client(
            url=self._backend_url, refresh_token=bearer, cache_dir=self._cache_dir
        )
        if cache_key:
            self._cache.put(cache_key, client, time.time() + 300)
        return client

    def close(self) -> None:
        """Evict all cached clients."""
        self._cache.close()


class BrokerServiceXClientFactory(ServiceXClientFactory):
    """Broker-mode HTTP factory: builds and caches one broker-backed ServiceXClient per MCP session.

    The client bearer this factory extracts is an AF Broker Identity Token
    (forwarded by the af-mcp-broker aggregator, which already authenticated
    the caller), not a ServiceX personal refresh token — the actual
    ServiceX access token is redeemed from the broker's own
    ``POST /v1/credentials/servicex/redeem`` (maniaclab/af-mcp-platform#295)
    via *redeemer*, lazily, the first time the returned client makes a real
    ServiceX call (see ``_BrokerServiceXAdapter``). *redeemer* is injected
    rather than constructed here so this class stays independent of
    af-credentials' concrete ``ProxyClient``, whose ``kind="servicex"``
    support is still landing (maniaclab/af-credentials#9) — the caller
    (``server.py``) wires the concrete redeemer.
    """

    def __init__(
        self,
        *,
        cache: SessionCache,
        redeemer: ServiceXRedeemer,
        backend_url: str,
        cache_dir: str,
    ) -> None:
        """Store the session cache, redeemer, backend URL, and download cache directory."""
        self._cache = cache
        self._redeemer = redeemer
        self._backend_url = backend_url
        self._cache_dir = cache_dir

    def get_client(self, ctx: Any) -> ServiceXClient:
        """Return a cached or newly built ServiceXClient for this session.

        Mirrors ``BearerTokenClientFactory.get_client`` exactly (same
        cache-key binding, same fixed 300s session TTL) — no redeem call
        happens here. The difference is entirely inside the adapter:
        ``_BrokerServiceXAdapter`` redeems from the broker on first real use
        and whenever its cached access token nears its own expiry, rather
        than exchanging a refresh token with ServiceX directly.
        """
        session_id, bearer = _extract_request_auth(ctx)
        cache_key = _cache_key(session_id, bearer) if session_id else None
        cached = self._cache.get(cache_key) if cache_key else None
        if cached is not None:
            return cached
        client = build_broker_servicex_client(
            url=self._backend_url,
            redeemer=self._redeemer,
            bearer=bearer,
            cache_dir=self._cache_dir,
        )
        if cache_key:
            self._cache.put(cache_key, client, time.time() + 300)
        return client

    def close(self) -> None:
        """Evict all cached clients."""
        self._cache.close()
