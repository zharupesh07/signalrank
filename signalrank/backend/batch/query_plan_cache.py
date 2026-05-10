from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import QueryPlanCache, gen_uuid
from batch import query_builder
from batch.query_builder import QUERY_PLAN_DEBUG_KEY, SearchQuery
from domain.artifact_versions import QUERY_PLAN_VERSION, query_plan_cache_key


def _queries_to_payload(queries: list[SearchQuery]) -> list[dict]:
    return [asdict(query) for query in queries]


def _cache_payload(
    queries: list[SearchQuery],
    *,
    shadow_payload: dict | None = None,
) -> dict:
    payload = {"queries": _queries_to_payload(queries)}
    if shadow_payload:
        payload[QUERY_PLAN_DEBUG_KEY] = shadow_payload
    return payload


def _payload_to_queries(payload: object) -> list[SearchQuery]:
    if isinstance(payload, dict):
        payload = payload.get("queries") or []
    if not isinstance(payload, list):
        return []
    queries: list[SearchQuery] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        location = str(item.get("location") or "").strip()
        country = str(item.get("country") or "").strip()
        if term:
            queries.append(SearchQuery(term=term, location=location, country=country))
    return queries


async def load_query_plan_cache(
    db: AsyncSession,
    *,
    profile_fingerprint: str,
    search_window_days: int,
    source_filter: str,
    requested_max_terms: int,
    query_version: str = QUERY_PLAN_VERSION,
) -> list[SearchQuery] | None:
    cache_key = query_plan_cache_key(
        profile_fingerprint=profile_fingerprint,
        search_window_days=search_window_days,
        source_filter=source_filter,
        query_version=query_version,
    )
    result = await db.execute(
        select(QueryPlanCache.query_payload, QueryPlanCache.max_terms)
        .where(QueryPlanCache.cache_key == cache_key)
        .limit(1)
    )
    row = result.first()
    if not row:
        return None
    payload, max_terms = row
    if int(max_terms or 0) < int(requested_max_terms or 0):
        return None
    queries = _payload_to_queries(payload)
    return queries[:requested_max_terms] if requested_max_terms else queries


async def store_query_plan_cache(
    db: AsyncSession,
    *,
    profile_fingerprint: str,
    search_window_days: int,
    source_filter: str,
    max_terms: int,
    queries: list[SearchQuery],
    shadow_payload: dict | None = None,
    query_version: str = QUERY_PLAN_VERSION,
) -> None:
    cache_key = query_plan_cache_key(
        profile_fingerprint=profile_fingerprint,
        search_window_days=search_window_days,
        source_filter=source_filter,
        query_version=query_version,
    )
    payload = _cache_payload(queries, shadow_payload=shadow_payload)
    stmt = pg_insert(QueryPlanCache).values(
        id=gen_uuid(),
        cache_key=cache_key,
        profile_fingerprint=profile_fingerprint,
        search_window_days=search_window_days,
        source_filter=source_filter,
        query_version=query_version,
        max_terms=max_terms,
        query_payload=payload,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cache_key"],
        set_={
            "profile_fingerprint": stmt.excluded.profile_fingerprint,
            "search_window_days": stmt.excluded.search_window_days,
            "source_filter": stmt.excluded.source_filter,
            "query_version": stmt.excluded.query_version,
            "max_terms": stmt.excluded.max_terms,
            "query_payload": stmt.excluded.query_payload,
        },
    )
    await db.execute(stmt)
    await db.commit()


async def get_cached_queries(
    db: AsyncSession,
    *,
    profile,
    profile_fingerprint: str,
    search_window_days: int,
    source_filter: str,
    max_terms: int,
) -> list[SearchQuery]:
    cached = await load_query_plan_cache(
        db,
        profile_fingerprint=profile_fingerprint,
        search_window_days=search_window_days,
        source_filter=source_filter,
        requested_max_terms=max_terms,
    )
    if cached is not None:
        return cached
    queries = query_builder.build_queries(profile, max_terms=max_terms)
    shadow_payload = query_builder.build_query_plan_debug(profile)
    if profile_fingerprint:
        await store_query_plan_cache(
            db,
            profile_fingerprint=profile_fingerprint,
            search_window_days=search_window_days,
            source_filter=source_filter,
            max_terms=max_terms,
            queries=queries,
            shadow_payload=shadow_payload,
        )
    return queries
