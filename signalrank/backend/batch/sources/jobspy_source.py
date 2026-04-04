from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)


def _effective_hours_old(config: ScraperConfig, site: str) -> int:
    return min(config.hours_old, 168) if site == "linkedin" else config.hours_old


async def _load_cached_jobs(
    db: AsyncSession | None,
    *,
    query: SearchQuery,
    config: ScraperConfig,
    site: str,
) -> list[RawJob] | None:
    cached = await load_cached_jobs(db, provider="jobspy", site=site, query=query, config=config)
    if cached is None:
        return None
    logger.info("JobSpy %s cache hit for %s/%s: %d jobs", site, query.term, query.location, len(cached))
    return cached


async def _store_cached_jobs(
    db: AsyncSession | None,
    *,
    query: SearchQuery,
    config: ScraperConfig,
    site: str,
    jobs: list[RawJob],
) -> None:
    await store_cached_jobs(db, provider="jobspy", site=site, query=query, config=config, jobs=jobs)


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
