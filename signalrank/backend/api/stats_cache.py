from __future__ import annotations

import time
from typing import Any

from api.config import settings

_STATS_CACHE_TTL_SECONDS = int(getattr(settings, "stats_cache_ttl_seconds", 30))
_stats_cache: dict[str, tuple[float, Any]] = {}
_MONOTONIC = time.monotonic


def get_cached_stats(key: str):
    cached = _stats_cache.get(key)
    if not cached:
        return None
    stored_at, payload = cached
    if (_MONOTONIC() - stored_at) >= _STATS_CACHE_TTL_SECONDS:
        _stats_cache.pop(key, None)
        return None
    return payload


def set_cached_stats(key: str, payload: Any) -> None:
    _stats_cache[key] = (_MONOTONIC(), payload)


def invalidate_stats_cache(*keys: str) -> None:
    if keys:
        for key in keys:
            _stats_cache.pop(key, None)
        return
    _stats_cache.clear()
