"""In-memory state store for in-flight OAuth bridge sessions.

Each bridge session tracks the lifecycle of one user's authentication:
  pending  →  (pasted ServiceX refresh token validated)  →  done
  pending  →  (invalid token / error)                    →  error

Unlike rucio-mcp's bridge (which polls an external IdP redirect), validation
here is synchronous: the /bridge form POST validates the token against
ServiceX's own /token/refresh in the same request, so sessions move from
pending to done/error within a single request-response cycle — there is no
background polling task.

Sessions are evicted after 5 minutes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class BridgeSession:
    """State for one in-flight bridge session."""

    session_id: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    client_id: str
    scopes: list[str]
    resource: str | None
    state: str | None
    expires_at: float
    status: str = "pending"  # "pending" | "done" | "error"
    servicex_token: str | None = None
    auth_code: str | None = None
    error_message: str | None = None


class BridgeStateStore:
    """Thread-safe in-memory store for :class:`BridgeSession` objects."""

    _TTL: float = 300.0

    def __init__(self) -> None:
        """Initialize thread-safe in-memory store."""
        self._lock = threading.Lock()
        self._by_session: dict[str, BridgeSession] = {}
        self._by_code: dict[str, str] = {}

    def put(self, session: BridgeSession) -> None:
        """Store *session*, replacing any existing entry with the same ID."""
        with self._lock:
            self._evict_locked()
            self._by_session[session.session_id] = session

    def get_by_session_id(self, session_id: str) -> BridgeSession | None:
        """Return the session or ``None`` if it does not exist or has expired."""
        with self._lock:
            self._evict_locked()
            return self._by_session.get(session_id)

    def get_by_auth_code(self, auth_code: str) -> BridgeSession | None:
        """Return the session associated with *auth_code*, or ``None`` if expired."""
        with self._lock:
            session_id = self._by_code.get(auth_code)
            if session_id is None:
                return None
            session = self._by_session.get(session_id)
            if session is not None and session.expires_at <= time.time():
                self._by_session.pop(session_id, None)
                self._by_code.pop(auth_code, None)
                return None
            return session

    def pop_by_auth_code(self, auth_code: str) -> BridgeSession | None:
        """Atomically remove and return the session for *auth_code* (single-use)."""
        with self._lock:
            session_id = self._by_code.pop(auth_code, None)
            if session_id is None:
                return None
            return self._by_session.pop(session_id, None)

    def mark_done(
        self, session_id: str, *, servicex_token: str, auth_code: str
    ) -> None:
        """Transition *session_id* to ``done`` and register the auth code index."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "done"
            s.servicex_token = servicex_token
            s.auth_code = auth_code
            self._by_code[auth_code] = session_id

    def mark_error(self, session_id: str, message: str) -> None:
        """Transition *session_id* to ``error`` with a human-readable *message*."""
        with self._lock:
            s = self._by_session.get(session_id)
            if s is None:
                return
            s.status = "error"
            s.error_message = message

    def session_counts(self) -> dict[str, int]:
        """Return a count of live sessions keyed by status."""
        with self._lock:
            self._evict_locked()
            counts: dict[str, int] = {}
            for s in self._by_session.values():
                counts[s.status] = counts.get(s.status, 0) + 1
            return counts

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._by_session.items() if s.expires_at <= now]
        for sid in expired:
            s = self._by_session.pop(sid)
            if s.auth_code:
                self._by_code.pop(s.auth_code, None)
