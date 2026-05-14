from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, ScrapeQueryCache
from api.sql_compat import dialect_insert
from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig


def normalize_cache_value(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def effective_hours_old(config: ScraperConfig, site: str) -> int:
    return min(config.hours_old, 168) if site == "linkedin" else config.hours_old


def cache_fresh_until(hours_old: int) -> datetime:
    ttl_hours = min(max(hours_old // 4, 1), 24)
    return datetime.now(timezone.utc) + timedelta(hours=ttl_hours)


def raw_job_to_raw(row: JobRaw) -> RawJob:
    return RawJob(
        job_url=row.job_url,
        title=row.title,
        company=row.company,
        description=row.description,
        location=row.location,
        site=row.site or "jobspy",
        date_posted=row.date_posted,
        availability_urls=row.availability_urls or [row.job_url],
    )


async def load_cached_jobs(
    db: AsyncSession | None,
    *,
    provider: str,
    site: str,
    query: SearchQuery,
    config: ScraperConfig,
) -> list[RawJob] | None:
    if db is None:
        return None
    now = datetime.now(timezone.utc)
    hours_old = effective_hours_old(config, site)
    stmt = (
        select(ScrapeQueryCache)
        .where(
            ScrapeQueryCache.provider == provider,
            ScrapeQueryCache.site == site,
            ScrapeQueryCache.term_normalized == normalize_cache_value(query.term),
            ScrapeQueryCache.location_normalized == normalize_cache_value(query.location),
            ScrapeQueryCache.country_normalized == normalize_cache_value(query.country),
            ScrapeQueryCache.hours_old == hours_old,
            ScrapeQueryCache.fresh_until >= now,
        )
        .limit(1)
    )
    cache_row = (await db.execute(stmt)).scalar_one_or_none()
    if cache_row is None:
        return None

    cached_urls = [str(url).strip() for url in (cache_row.result_job_urls or []) if str(url).strip()]
    if not cached_urls:
        return []

    rows = await db.execute(select(JobRaw).where(JobRaw.job_url.in_(cached_urls)))
    jobs_by_url = {row.job_url: raw_job_to_raw(row) for row in rows.scalars().all()}
    if len(jobs_by_url) != len(cached_urls):
        return None
    return [jobs_by_url[url] for url in cached_urls if url in jobs_by_url]


async def store_cached_jobs(
    db: AsyncSession | None,
    *,
    provider: str,
    site: str,
    query: SearchQuery,
    config: ScraperConfig,
    jobs: list[RawJob],
) -> None:
    if db is None:
        return

    hours_old = effective_hours_old(config, site)
    job_urls = [job.job_url for job in jobs if job.job_url]
    stmt = (
        dialect_insert(db, ScrapeQueryCache)
        .values(
            provider=provider,
            site=site,
            term_normalized=normalize_cache_value(query.term),
            location_normalized=normalize_cache_value(query.location),
            country_normalized=normalize_cache_value(query.country),
            hours_old=hours_old,
            result_job_urls=job_urls,
            result_count=len(job_urls),
            fresh_until=cache_fresh_until(hours_old),
        )
        .on_conflict_do_update(
            index_elements=[
                ScrapeQueryCache.provider,
                ScrapeQueryCache.site,
                ScrapeQueryCache.term_normalized,
                ScrapeQueryCache.location_normalized,
                ScrapeQueryCache.country_normalized,
                ScrapeQueryCache.hours_old,
            ],
            set_={
                "result_job_urls": job_urls,
                "result_count": len(job_urls),
                "searched_at": datetime.now(timezone.utc),
                "fresh_until": cache_fresh_until(hours_old),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
