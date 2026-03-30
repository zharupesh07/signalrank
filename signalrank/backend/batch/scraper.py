from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

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


async def scrape(
    queries: list[SearchQuery],
    config: ScraperConfig,
    on_progress: Callable | None = None,
    on_persist: Callable | None = None,
) -> list[RawJob]:
    from batch.sources.rapidapi import search as search_rapidapi
    from batch.sources.jobspy_source import search as search_jobspy
    from batch.sources.free_apis import search as search_free
    from batch.sources.google_jobs import search as search_google

    all_jobs: list[RawJob] = []
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
        all_jobs.extend(filtered)

    allowed = set(config.sources) if config.sources else None

    async def _run():
        # Phase 1: JobSpy Indeed
        if not allowed or "indeed" in allowed:
            if on_progress:
                await on_progress(
                    phase="jobspy_indeed", phase_num=1, total_phases=3,
                    jobs_found=0, message="Scanning Indeed...",
                )
            try:
                results = await asyncio.wait_for(search_jobspy(queries, config, site="indeed"), timeout=config.jobspy_timeout)
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
                    jobs_found=len(all_jobs), message="Scanning LinkedIn...",
                )
            try:
                results = await asyncio.wait_for(search_jobspy(linkedin_queries, config, site="linkedin"), timeout=config.jobspy_timeout)
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
                    jobs_found=len(all_jobs), message="Scanning additional sources...",
                )
            parallel_sources = [
                ("rapidapi", search_rapidapi),
                ("free_apis", search_free),
                ("google_jobs", search_google),
            ]
            if allowed:
                parallel_sources = [(n, fn) for n, fn in parallel_sources if n in allowed]
            tasks = [fn(queries, config) for _, fn in parallel_sources]
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
        logger.warning("Scrape timed out after 900s, returning %d jobs", len(all_jobs))

    logger.info("Scrape complete: %d jobs (deduped+filtered per phase)", len(all_jobs))
    return all_jobs
