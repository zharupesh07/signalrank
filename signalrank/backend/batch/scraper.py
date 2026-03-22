from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

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
    max_results_per_query: int = 1000
    hours_old: int = 720
    jobspy_delay: float = 1.0
    google_delay: float = 2.0
    title_blocklist: list[str] = field(default_factory=list)
    # 0 = disabled, N = run only first N queries on LinkedIn (slow ~80s/query)
    linkedin_max_queries: int = 0

    @classmethod
    def from_env(cls, title_blocklist: list[str] | None = None) -> ScraperConfig:
        return cls(
            rapidapi_key=os.environ.get("RAPIDAPI_KEY"),
            max_results_per_query=int(os.environ.get("SCRAPER_MAX_RESULTS", "1000")),
            hours_old=int(os.environ.get("SCRAPER_HOURS_OLD", "720")),
            linkedin_max_queries=int(os.environ.get("LINKEDIN_MAX_QUERIES", "0")),
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
) -> list[RawJob]:
    from batch.sources.rapidapi import search as search_rapidapi
    from batch.sources.jobspy_source import search as search_jobspy
    from batch.sources.free_apis import search as search_free
    from batch.sources.google_jobs import search as search_google

    all_jobs: list[RawJob] = []

    async def _run():
        # Phase 1: JobSpy Indeed (fast, 30-day lookback)
        if on_progress:
            await on_progress(
                phase="jobspy_indeed", phase_num=1, total_phases=3,
                jobs_found=0, message="Scanning Indeed...",
            )
        try:
            results = await asyncio.wait_for(search_jobspy(queries, config, site="indeed"), timeout=3600)
            all_jobs.extend(results)
            logger.info("Phase jobspy/indeed: %d jobs", len(results))
        except asyncio.TimeoutError:
            logger.warning("Phase jobspy/indeed timed out")
        except Exception:
            logger.exception("Phase jobspy/indeed failed, skipping")

        # Phase 2: JobSpy LinkedIn (slower, 7-day lookback) — skipped if linkedin_max_queries=0
        if config.linkedin_max_queries > 0:
            linkedin_queries = queries[:config.linkedin_max_queries]
            if on_progress:
                await on_progress(
                    phase="jobspy_linkedin", phase_num=2, total_phases=3,
                    jobs_found=len(all_jobs), message="Scanning LinkedIn...",
                )
            try:
                results = await asyncio.wait_for(search_jobspy(linkedin_queries, config, site="linkedin"), timeout=3600)
                all_jobs.extend(results)
                logger.info("Phase jobspy/linkedin: %d jobs", len(results))
            except asyncio.TimeoutError:
                logger.warning("Phase jobspy/linkedin timed out")
            except Exception:
                logger.exception("Phase jobspy/linkedin failed, skipping")
        else:
            logger.info("Phase jobspy/linkedin: skipped (linkedin_max_queries=0)")

        # Phase 3: Parallel sources
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
        tasks = [fn(queries, config) for _, fn in parallel_sources]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        for (name, _), res in zip(parallel_sources, results_list):
            if isinstance(res, Exception):
                logger.exception("Phase %s failed: %s", name, res)
            else:
                all_jobs.extend(res)
                logger.info("Phase %s: %d jobs", name, len(res))

    try:
        await asyncio.wait_for(_run(), timeout=7200)
    except asyncio.TimeoutError:
        logger.warning("Scrape timed out after 7200s, returning %d jobs", len(all_jobs))

    seen_urls: set[str] = set()
    deduped: list[RawJob] = []
    for job in all_jobs:
        if job.job_url not in seen_urls:
            seen_urls.add(job.job_url)
            deduped.append(job)

    filtered = [
        j for j in deduped
        if not _is_blocked(j.title, config.title_blocklist)
    ]

    logger.info(
        "Scrape complete: %d raw -> %d deduped -> %d filtered",
        len(all_jobs), len(deduped), len(filtered),
    )
    return filtered
