"""Tests for SessionCache."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from servicex_mcp.auth.session_cache import SessionCache


class TestSessionCacheClosesQueryCacheOnEviction:
    def test_expired_entry_closes_query_cache_on_get(self) -> None:
        cache = SessionCache()
        client = MagicMock()
        cache.put("sid-1", client, time.time() - 1)
        assert cache.get("sid-1") is None
        client.query_cache.close.assert_called_once()

    def test_expired_entry_closes_query_cache_on_evict_locked(self) -> None:
        cache = SessionCache()
        stale_client = MagicMock()
        cache.put("stale", stale_client, time.time() - 1)
        # A fresh put() triggers _evict_locked(), not a get() on "stale".
        cache.put("fresh", MagicMock(), time.time() + 3600)
        stale_client.query_cache.close.assert_called_once()

    def test_close_closes_query_cache_for_every_remaining_entry(self) -> None:
        cache = SessionCache()
        client_a = MagicMock()
        client_b = MagicMock()
        cache.put("a", client_a, time.time() + 3600)
        cache.put("b", client_b, time.time() + 3600)
        cache.close()
        client_a.query_cache.close.assert_called_once()
        client_b.query_cache.close.assert_called_once()

    def test_a_failing_close_does_not_break_eviction(self) -> None:
        cache = SessionCache()
        broken_client = MagicMock()
        broken_client.query_cache.close.side_effect = RuntimeError("db already closed")
        cache.put("broken", broken_client, time.time() - 1)
        # Must not raise, and the entry must still be evicted.
        assert cache.get("broken") is None


class TestSessionCache:
    def test_put_and_get_round_trip(self) -> None:
        cache = SessionCache()
        client = MagicMock()
        cache.put("sid-1", client, time.time() + 3600)
        assert cache.get("sid-1") is client

    def test_get_returns_none_for_unknown_session(self) -> None:
        cache = SessionCache()
        assert cache.get("no-such-session") is None

    def test_expired_entry_is_evicted_on_get(self) -> None:
        cache = SessionCache()
        client = MagicMock()
        # expires in the past
        cache.put("sid-expired", client, time.time() - 1)
        assert cache.get("sid-expired") is None

    def test_close_clears_all_entries(self) -> None:
        cache = SessionCache()
        cache.put("a", MagicMock(), time.time() + 3600)
        cache.put("b", MagicMock(), time.time() + 3600)
        cache.close()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_size_empty(self) -> None:
        cache = SessionCache()
        assert cache.size() == 0

    def test_size_counts_live_entries(self) -> None:
        cache = SessionCache()
        cache.put("a", MagicMock(), time.time() + 3600)
        cache.put("b", MagicMock(), time.time() + 3600)
        assert cache.size() == 2

    def test_size_excludes_expired_entries(self) -> None:
        cache = SessionCache()
        cache.put("fresh", MagicMock(), time.time() + 3600)
        cache.put("stale", MagicMock(), time.time() - 1)
        assert cache.size() == 1

    def test_put_proactively_evicts_expired_entries_not_just_at_get(self) -> None:
        # A session whose key is never queried again after expiry must not
        # sit in the dict forever holding its client/token state.
        cache = SessionCache()
        cache.put("sid-stale", MagicMock(), time.time() - 1)
        assert len(cache._data) == 1
        cache.put("sid-fresh", MagicMock(), time.time() + 3600)
        assert len(cache._data) == 1
        assert "sid-stale" not in cache._data

    def test_concurrent_access_does_not_corrupt(self) -> None:
        cache = SessionCache()
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                client = MagicMock()
                cache.put(f"sid-{i}", client, time.time() + 3600)
                result = cache.get(f"sid-{i}")
                assert result is client
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
