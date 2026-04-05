import time

import api.stats_cache as stats_cache
from api.stats_cache import get_cached_stats, invalidate_stats_cache, set_cached_stats


def test_stats_cache_roundtrip_and_invalidation():
    key = "unit-test-stats"
    payload = {"total": 3}

    invalidate_stats_cache()
    assert get_cached_stats(key) is None

    set_cached_stats(key, payload)
    assert get_cached_stats(key) == payload

    invalidate_stats_cache(key)
    assert get_cached_stats(key) is None


def test_stats_cache_expires(monkeypatch):
    key = "unit-test-stats-expire"
    payload = {"total": 7}
    set_cached_stats(key, payload)
    assert get_cached_stats(key) == payload

    monkeypatch.setattr(stats_cache, "_MONOTONIC", lambda: time.monotonic() + 10_000)
    assert get_cached_stats(key) is None
