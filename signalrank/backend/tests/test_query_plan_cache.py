import pytest
from unittest.mock import AsyncMock, MagicMock

from batch.query_builder import SearchQuery
from batch.query_plan_cache import get_cached_queries

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_get_cached_queries_uses_existing_cache(monkeypatch):
    cached = [SearchQuery(term="Engineer", location="Pune", country="India")]
    monkeypatch.setattr("batch.query_plan_cache.load_query_plan_cache", AsyncMock(return_value=cached))
    build_queries = MagicMock()
    monkeypatch.setattr("batch.query_plan_cache.query_builder.build_queries", build_queries)

    db = MagicMock()
    result = await get_cached_queries(
        db,
        profile=MagicMock(),
        profile_fingerprint="fp",
        search_window_days=7,
        source_filter="indeed",
        max_terms=1,
    )

    assert result == cached
    build_queries.assert_not_called()


@pytest.mark.asyncio
async def test_get_cached_queries_builds_and_stores_when_missing(monkeypatch):
    cached = None
    monkeypatch.setattr("batch.query_plan_cache.load_query_plan_cache", AsyncMock(return_value=cached))
    build_queries = MagicMock(return_value=[SearchQuery(term="Engineer", location="", country="India")])
    store_query_plan_cache = AsyncMock()
    monkeypatch.setattr("batch.query_plan_cache.query_builder.build_queries", build_queries)
    monkeypatch.setattr("batch.query_plan_cache.store_query_plan_cache", store_query_plan_cache)

    db = MagicMock()
    result = await get_cached_queries(
        db,
        profile=MagicMock(),
        profile_fingerprint="fp",
        search_window_days=7,
        source_filter="indeed",
        max_terms=1,
    )

    assert result == [SearchQuery(term="Engineer", location="", country="India")]
    build_queries.assert_called_once()
    store_query_plan_cache.assert_awaited_once()
