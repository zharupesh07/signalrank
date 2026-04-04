from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, ScrapeQueryCache
from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)


def _normalize_cache_value(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _effective_hours_old(config: ScraperConfig, site: str) -> int:
    return min(config.hours_old, 168) if site == "linkedin" else config.hours_old


def _cache_fresh_until(hours_old: int) -> datetime:
    ttl_hours = min(max(hours_old // 4, 1), 24)
    return datetime.now(timezone.utc) + timedelta(hours=ttl_hours)


def _to_raw_job(row: JobRaw) -> RawJob:
    return RawJob(
        job_url=row.job_url,
        title=row.title,
        company=row.company,
        description=row.description,
        location=row.location,
        site=row.site or "jobspy",
        date_posted=row.date_posted,
    )


async def _load_cached_jobs(
    db: AsyncSession | None,
    *,
    query: SearchQuery,
    config: ScraperConfig,
    site: str,
) -> list[RawJob] | None:
    if db is None:
        return None
    now = datetime.now(timezone.utc)
    hours_old = _effective_hours_old(config, site)
    stmt = (
        select(ScrapeQueryCache)
        .where(
            ScrapeQueryCache.provider == "jobspy",
            ScrapeQueryCache.site == site,
            ScrapeQueryCache.term_normalized == _normalize_cache_value(query.term),
            ScrapeQueryCache.location_normalized == _normalize_cache_value(query.location),
            ScrapeQueryCache.country_normalized == _normalize_cache_value(query.country),
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
        logger.info("JobSpy %s cache hit for %s/%s: 0 jobs", site, query.term, query.location)
        return []

    rows = await db.execute(select(JobRaw).where(JobRaw.job_url.in_(cached_urls)))
    jobs_by_url = {row.job_url: _to_raw_job(row) for row in rows.scalars().all()}
    if len(jobs_by_url) != len(cached_urls):
        logger.info("JobSpy %s cache stale for %s/%s, refreshing", site, query.term, query.location)
        return None

    logger.info("JobSpy %s cache hit for %s/%s: %d jobs", site, query.term, query.location, len(cached_urls))
    return [jobs_by_url[url] for url in cached_urls if url in jobs_by_url]


async def _store_cached_jobs(
    db: AsyncSession | None,
    *,
    query: SearchQuery,
    config: ScraperConfig,
    site: str,
    jobs: list[RawJob],
) -> None:
    if db is None:
        return

    hours_old = _effective_hours_old(config, site)
    job_urls = [job.job_url for job in jobs if job.job_url]
    stmt = (
        pg_insert(ScrapeQueryCache)
        .values(
            provider="jobspy",
            site=site,
            term_normalized=_normalize_cache_value(query.term),
            location_normalized=_normalize_cache_value(query.location),
            country_normalized=_normalize_cache_value(query.country),
            hours_old=hours_old,
            result_job_urls=job_urls,
            result_count=len(job_urls),
            fresh_until=_cache_fresh_until(hours_old),
        )
        .on_conflict_do_update(
            constraint="uq_scrape_query_cache_key",
            set_={
                "result_job_urls": job_urls,
                "result_count": len(job_urls),
                "searched_at": datetime.now(timezone.utc),
                "fresh_until": _cache_fresh_until(hours_old),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()


def _scrape_sync(term: str, location: str, country: str, config: ScraperConfig, site: str = "indeed") -> list[RawJob]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.warning("python-jobspy not installed, skipping")
        return []

    hours_old = _effective_hours_old(config, site)

    try:
        df = scrape_jobs(
            site_name=[site],
            search_term=term,
            location=location,
            results_wanted=config.max_results_per_query,
            hours_old=hours_old,
            country_indeed=country,
        )
    except Exception:
        logger.exception("JobSpy scrape failed for %s / %s / %s", site, term, location)
        return []

    jobs = []
    for _, row in df.iterrows():
        direct = str(row.get("job_url_direct") or "").strip()
        fallback = str(row.get("job_url") or "").strip()
        # Prefer company portal URL; fall back to Indeed; last resort LinkedIn
        if direct and "linkedin.com" not in direct:
            url = direct
        elif fallback and "linkedin.com" not in fallback:
            url = fallback
        else:
            url = direct or fallback
        if not url:
            continue
        date_posted = None
        raw_date = row.get("date_posted")
        if raw_date is not None:
            try:
                if hasattr(raw_date, "to_pydatetime"):
                    date_posted = raw_date.to_pydatetime()
                    if date_posted.tzinfo is None:
                        date_posted = date_posted.replace(tzinfo=timezone.utc)
                else:
                    date_posted = datetime.fromisoformat(str(raw_date))
            except (ValueError, TypeError):
                pass

        jobs.append(RawJob(
            job_url=url,
            title=str(row.get("title", "")) or None,
            company=str(row.get("company", "")) or None,
            description=str(row.get("description", "")) or None,
            location=str(row.get("location", "")) or None,
            site=str(row.get("site", "jobspy")),
            date_posted=date_posted,
        ))
    return jobs


async def search(
    queries: list[SearchQuery],
    config: ScraperConfig,
    site: str = "indeed",
    db: AsyncSession | None = None,
) -> list[RawJob]:
    timeout = 120 if site == "linkedin" else 30
    all_jobs: list[RawJob] = []
    for query in queries:
        cached = await _load_cached_jobs(db, query=query, config=config, site=site)
        if cached is not None:
            all_jobs.extend(cached)
            continue
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_scrape_sync, query.term, query.location, query.country, config, site),
                timeout=timeout,
            )
            await _store_cached_jobs(db, query=query, config=config, site=site, jobs=result)
            all_jobs.extend(result)
            logger.info("JobSpy %s %s/%s: %d jobs", site, query.term, query.location, len(result))
        except asyncio.TimeoutError:
            logger.warning("JobSpy %s timeout for %s / %s", site, query.term, query.location)
        except Exception:
            logger.exception("JobSpy %s failed for %s / %s", site, query.term, query.location)
        await asyncio.sleep(config.jobspy_delay)
    return all_jobs
