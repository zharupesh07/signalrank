from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.config import settings
from batch.query_builder import SearchQuery

logger = logging.getLogger(__name__)


@dataclass
class RawJob:
    """Transport object for scraped job data. NOT an ORM model."""
    job_url: str
    title: str | None
    company: str | None
    description: str | None
    location: str | None
    site: str
    date_posted: datetime | None


def raw_job_to_dict(job: RawJob) -> dict:
    return {
        "job_url": job.job_url,
        "title": job.title,
        "company": job.company,
        "description": job.description,
        "location": job.location,
        "site": job.site,
        "date_posted": job.date_posted,
    }


@dataclass
class ScraperConfig:
    rapidapi_key: str | None = None
    max_results_per_query: int = 1500
    hours_old: int = 24
    jobspy_delay: float = 1.0
    google_delay: float = 2.0
    title_blocklist: list[str] = field(default_factory=list)
    # 0 = disabled, N = run only first N queries on LinkedIn (slow ~80s/query)
    linkedin_max_queries: int = 0
    default_country: str = "India"
    sources: list[str] | None = None  # None = all; e.g. ["indeed"] for quick run
    jobspy_timeout: int = 300
    total_timeout: int = 900

    @classmethod
    def from_env(cls, title_blocklist: list[str] | None = None) -> ScraperConfig:
        return cls(
            rapidapi_key=settings.rapidapi_key or None,
            max_results_per_query=settings.scraper_max_results,
            hours_old=settings.scraper_hours_old,
            linkedin_max_queries=settings.linkedin_max_queries,
            default_country=settings.scraper_default_country,
            title_blocklist=title_blocklist or [],
        )


def _is_blocked(title: str | None, blocklist: list[str]) -> bool:
    if not title or not blocklist:
        return False
    lower = title.lower()
    return any(b.lower() in lower for b in blocklist)


def _dedupe_query_terms(queries: list[SearchQuery]) -> list[SearchQuery]:
    seen_terms: set[str] = set()
    unique_queries: list[SearchQuery] = []
    for query in queries:
        key = query.term.lower()
        if key in seen_terms:
            continue
        seen_terms.add(key)
        unique_queries.append(query)
    return unique_queries


async def _cached_urls_for_assignment(
    db: AsyncSession,
    *,
    provider: str,
    site: str,
    query: SearchQuery,
    config: ScraperConfig,
) -> list[str] | None:
    from batch.scrape_cache import load_cached_jobs

    cached = await load_cached_jobs(
        db,
        provider=provider,
        site=site,
        query=query,
        config=config,
    )
    if cached is None:
        return None
    return [job.job_url for job in cached if job.job_url]


async def plan_incremental_scrape(
    queries: list[SearchQuery],
    config: ScraperConfig,
    db: AsyncSession | None,
) -> tuple[list[SearchQuery], list[str]]:
    if db is None or not queries:
        return queries, []

    allowed = set(config.sources) if config.sources else None
    stale_indexes: set[int] = set()
    cached_urls: list[str] = []
    seen_cached_urls: set[str] = set()

    async def _record_assignment(
        query_index: int,
        *,
        provider: str,
        site: str,
        query: SearchQuery,
    ) -> None:
        urls = await _cached_urls_for_assignment(
            db,
            provider=provider,
            site=site,
            query=query,
            config=config,
        )
        if urls is None:
            stale_indexes.add(query_index)
            return
        for url in urls:
            if url not in seen_cached_urls:
                seen_cached_urls.add(url)
                cached_urls.append(url)

    if not allowed or "indeed" in allowed:
        for idx, query in enumerate(queries):
            await _record_assignment(idx, provider="jobspy", site="indeed", query=query)

    if (not allowed or "linkedin" in allowed) and config.linkedin_max_queries > 0:
        for idx, query in enumerate(queries[:config.linkedin_max_queries]):
            await _record_assignment(idx, provider="jobspy", site="linkedin", query=query)

    if not allowed or "rapidapi" in allowed:
        from batch.sources.rapidapi import SOURCES, _partition_queries

        assignments = _partition_queries(queries, list(SOURCES.keys()))
        for idx, (site, query) in enumerate(assignments):
            await _record_assignment(idx, provider="rapidapi", site=site, query=query)

    if not allowed or "google_jobs" in allowed:
        for idx, query in enumerate(queries):
            await _record_assignment(idx, provider="google_jobs", site="google", query=query)

    if not allowed or "amazon_jobs" in allowed:
        for idx, query in enumerate(queries):
            await _record_assignment(idx, provider="amazon_jobs", site="amazon", query=query)

    if not allowed or "free_apis" in allowed:
        unique_queries = _dedupe_query_terms(queries)
        if unique_queries:
            himalayas_urls = await _cached_urls_for_assignment(
                db,
                provider="free_apis",
                site="himalayas",
                query=unique_queries[0],
                config=config,
            )
            if himalayas_urls is None:
                stale_indexes.add(0)
            else:
                for url in himalayas_urls:
                    if url not in seen_cached_urls:
                        seen_cached_urls.add(url)
                        cached_urls.append(url)

        term_to_indexes: dict[str, list[int]] = {}
        for idx, query in enumerate(queries):
            term_to_indexes.setdefault(query.term.lower(), []).append(idx)

        for query in unique_queries:
            remotive_urls = await _cached_urls_for_assignment(
                db,
                provider="free_apis",
                site="remotive",
                query=query,
                config=config,
            )
            jobicy_urls = await _cached_urls_for_assignment(
                db,
                provider="free_apis",
                site="jobicy",
                query=query,
                config=config,
            )
            if remotive_urls is None or jobicy_urls is None:
                stale_indexes.update(term_to_indexes.get(query.term.lower(), []))
                continue
            for url in [*remotive_urls, *jobicy_urls]:
                if url not in seen_cached_urls:
                    seen_cached_urls.add(url)
                    cached_urls.append(url)

    if not allowed or "workday" in allowed:
        from batch.sources.workday import active_companies

        for company in active_companies():
            for idx, query in enumerate(queries):
                await _record_assignment(
                    idx,
                    provider="workday",
                    site=company["slug"],
                    query=query,
                )

    stale_queries = [query for idx, query in enumerate(queries) if idx in stale_indexes]
    return stale_queries, cached_urls


async def scrape(
    queries: list[SearchQuery],
    config: ScraperConfig,
    on_progress: Callable | None = None,
    on_persist: Callable | None = None,
    db: AsyncSession | None = None,
    *,
    return_mode: str = "jobs",
) -> list[RawJob] | list[str]:
    from batch.sources.rapidapi import search as search_rapidapi
    from batch.sources.jobspy_source import search as search_jobspy
    from batch.sources.free_apis import search as search_free
    from batch.sources.google_jobs import search as search_google
    from batch.sources.amazon_jobs import search as search_amazon_jobs
    from batch.sources.ats_direct import search as search_ats_direct
    from batch.sources.workday import search as search_workday

    keep_urls_only = return_mode == "urls"
    all_results: list[RawJob] | list[str] = []
    seen_urls: set[str] = set()

    def _dedup_new(jobs: list[RawJob]) -> list[RawJob]:
        new = []
        for j in jobs:
            if j.job_url not in seen_urls:
                seen_urls.add(j.job_url)
                new.append(j)
        return new

    async def _persist_phase(phase_jobs: list[RawJob]) -> None:
        deduped = _dedup_new(phase_jobs)
        filtered = [j for j in deduped if not _is_blocked(j.title, config.title_blocklist)]
        if filtered and on_persist:
            await on_persist(filtered)
        if keep_urls_only:
            all_results.extend([j.job_url for j in filtered])
        else:
            all_results.extend(filtered)

    allowed = set(config.sources) if config.sources else None
    isolated_session_factory = async_sessionmaker(bind=db.bind, expire_on_commit=False) if db is not None else None

    async def _run_source_with_isolated_db(fn):
        if db is None:
            return await fn(queries, config, db=None)
        async with isolated_session_factory() as isolated_db:
            return await fn(queries, config, db=isolated_db)

    async def _run():
        # Phase 1: JobSpy Indeed
        if not allowed or "indeed" in allowed:
            if on_progress:
                await on_progress(
                    phase="jobspy_indeed", phase_num=1, total_phases=3,
                    jobs_found=0, message="Scanning Indeed...",
                )
            try:
                results = await asyncio.wait_for(search_jobspy(queries, config, site="indeed", db=db), timeout=config.jobspy_timeout)
                logger.info("Phase jobspy/indeed: %d jobs", len(results))
                await _persist_phase(results)
            except asyncio.TimeoutError:
                logger.warning("Phase jobspy/indeed timed out")
            except Exception:
                logger.exception("Phase jobspy/indeed failed, skipping")

        # Phase 2: JobSpy LinkedIn — skipped if linkedin_max_queries=0 or filtered out
        if (not allowed or "linkedin" in allowed) and config.linkedin_max_queries > 0:
            linkedin_queries = queries[:config.linkedin_max_queries]
            if on_progress:
                await on_progress(
                    phase="jobspy_linkedin", phase_num=2, total_phases=3,
                    jobs_found=len(all_results), message="Scanning LinkedIn...",
                )
            try:
                results = await asyncio.wait_for(search_jobspy(linkedin_queries, config, site="linkedin", db=db), timeout=config.jobspy_timeout)
                logger.info("Phase jobspy/linkedin: %d jobs", len(results))
                await _persist_phase(results)
            except asyncio.TimeoutError:
                logger.warning("Phase jobspy/linkedin timed out")
            except Exception:
                logger.exception("Phase jobspy/linkedin failed, skipping")
        else:
            logger.info("Phase jobspy/linkedin: skipped")

        # Phase 3: Parallel sources — skip if filtered
        if not allowed or allowed - {"indeed", "linkedin"}:
            if on_progress:
                await on_progress(
                    phase="parallel", phase_num=3, total_phases=3,
                    jobs_found=len(all_results), message="Scanning additional sources...",
                )
            parallel_sources = [
                ("ats_direct", search_ats_direct),
                ("workday", search_workday),
                ("rapidapi", search_rapidapi),
                ("free_apis", search_free),
                ("google_jobs", search_google),
                ("amazon_jobs", search_amazon_jobs),
            ]
            if allowed:
                parallel_sources = [(n, fn) for n, fn in parallel_sources if n in allowed]
            tasks = [_run_source_with_isolated_db(fn) for _, fn in parallel_sources]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for (name, _), res in zip(parallel_sources, results_list):
                if isinstance(res, Exception):
                    logger.exception("Phase %s failed: %s", name, res)
                else:
                    logger.info("Phase %s: %d jobs", name, len(res))
                    await _persist_phase(res)
        else:
            logger.info("Phase parallel: skipped (source filter)")

    try:
        await asyncio.wait_for(_run(), timeout=config.total_timeout)
    except asyncio.TimeoutError:
        logger.warning("Scrape timed out after 900s, returning %d jobs", len(all_results))

    logger.info("Scrape complete: %d jobs (deduped+filtered per phase)", len(all_results))
    return all_results
