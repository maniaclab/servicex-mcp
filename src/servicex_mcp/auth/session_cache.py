"""Per-session ServiceX client cache with fixed-TTL eviction."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from servicex.servicex_client import ServiceXClient


class SessionCache:
    """Thread-safe cache of ServiceXClient instances keyed by MCP session ID.

    Each entry expires at a caller-supplied absolute epoch (typically
    300 s from creation), so a new client is built once per session and
    evicted after the fixed TTL. Expired entries are swept on every `put`
    (not just lazily on `get` of that exact key), so a session whose key
    is never queried again after expiry doesn't hold its ServiceXClient
    (and the token state it carries) in memory indefinitely — same
    eviction discipline as `BridgeStateStore`.
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
            del self._data[sid]

    def size(self) -> int:
        """Return the number of unexpired entries currently in the cache."""
        now = time.time()
        with self._lock:
            return sum(1 for _, exp in self._data.values() if exp >= now)

    def close(self) -> None:
        """Evict all cached clients."""
        with self._lock:
            self._data.clear()
