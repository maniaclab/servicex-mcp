"""Per-session ServiceX client cache with fixed-TTL eviction."""

from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from servicex.servicex_client import ServiceXClient


def _close_client_resources(client: ServiceXClient) -> None:
    """Close the client's on-disk query cache (a real TinyDB file handle).

    `build_http_servicex_client` opens a fresh `QueryCache` — and therefore
    a real file handle — on every cache miss (see auth/factory.py). Nothing
    else in this codebase ever calls `client.query_cache.close()`, so
    eviction is the only place that can reliably release it; leaving this
    to CPython's refcounting GC is a latent fd-exhaustion risk under
    sustained concurrent HTTP load. Best-effort: a close failure must never
    break cache eviction itself.
    """
    query_cache = getattr(client, "query_cache", None)
    if query_cache is not None:
        with contextlib.suppress(Exception):
            query_cache.close()


class SessionCache:
    """Thread-safe cache of ServiceXClient instances keyed by MCP session ID.

    Each entry expires at a caller-supplied absolute epoch (typically
    300 s from creation), so a new client is built once per session and
    evicted after the fixed TTL. Expired entries are swept on every `put`
    (not just lazily on `get` of that exact key), so a session whose key
    is never queried again after expiry doesn't hold its ServiceXClient
    (and the token state it carries) in memory indefinitely — same
    eviction discipline as `BridgeStateStore`. Every eviction path also
    closes the evicted client's query cache (see `_close_client_resources`).
    """

    def __init__(self) -> None:
        """Initialise an empty cache with a threading lock."""
        self._lock = threading.Lock()
        self._data: dict[str, tuple[ServiceXClient, float]] = {}

    def get(self, session_id: str) -> ServiceXClient | None:
        """Return the cached client if present and unexpired, else None."""
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            client, exp = entry
            if exp < time.time():
                del self._data[session_id]
                _close_client_resources(client)
                return None
            return client

    def put(self, session_id: str, client: ServiceXClient, expires_at: float) -> None:
        """Store a client under session_id, expiring at the given epoch."""
        with self._lock:
            self._evict_locked()
            self._data[session_id] = (client, expires_at)

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, (_, exp) in self._data.items() if exp < now]
        for sid in expired:
            client, _ = self._data.pop(sid)
            _close_client_resources(client)

    def size(self) -> int:
        """Return the number of unexpired entries currently in the cache."""
        now = time.time()
        with self._lock:
            return sum(1 for _, exp in self._data.values() if exp >= now)

    def close(self) -> None:
        """Evict all cached clients, closing each one's query cache."""
        with self._lock:
            for client, _ in self._data.values():
                _close_client_resources(client)
            self._data.clear()
