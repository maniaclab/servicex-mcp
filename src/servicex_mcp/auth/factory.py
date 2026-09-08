"""ServiceX client factory: abstracts how the ServiceXClient is obtained per-request."""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from servicex.configuration import Configuration
from servicex.query_cache import QueryCache
from servicex.servicex_adapter import ServiceXAdapter
from servicex.servicex_client import ServiceXClient

if TYPE_CHECKING:
    from servicex_mcp.auth.session_cache import SessionCache


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
    client._code_generators = None
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
