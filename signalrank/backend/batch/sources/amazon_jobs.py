from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

_AMAZON_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
_AMAZON_PAGE_SIZE = 10


def _cache_query(query: SearchQuery, config: ScraperConfig) -> SearchQuery:
    return SearchQuery(
        term=query.term,
        location=query.location,
        country=query.country or config.default_country,
    )


def _search_url(query: SearchQuery, offset: int) -> str:
    params = [
        f"base_query={quote_plus(query.term or '')}",
        f"loc_query={quote_plus(query.location or query.country or '')}",
        f"offset={offset}",
    ]
    return f"{_AMAZON_SEARCH_URL}?{'&'.join(params)}"


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _matches_query(job: dict, query: SearchQuery) -> bool:
    title = str(job.get("title") or "")
    description = " ".join(
        str(part or "")
        for part in (
            job.get("description_short"),
            job.get("basic_qualifications"),
            job.get("preferred_qualifications"),
            job.get("description"),
        )
    )
    combined = f"{title} {description}".lower()
    raw_term = str(query.term or "").lower().strip()
    location = " ".join(
        str(part or "")
        for part in (
            job.get("normalized_location"),
            job.get("location"),
            job.get("city"),
            job.get("state"),
            job.get("country_code"),
        )
    ).lower()

    if raw_term and raw_term in combined:
        return not query.location or query.location.lower() in location

    tokens = [token for token in re.findall(r"[a-z0-9\+#/]+", raw_term) if token]
    if not tokens:
        return True
    overlap = sum(1 for token in tokens if token in combined)
    if overlap == 0:
        return False
    return not query.location or query.location.lower() in location


def _normalize_job(job: dict) -> RawJob | None:
    job_path = str(job.get("job_path") or "").strip()
    if not job_path:
        return None
    job_url = f"https://www.amazon.jobs{job_path}"
    location = str(job.get("normalized_location") or job.get("location") or "").strip() or None
    description = "\n\n".join(
        part
        for part in (
            job.get("description_short"),
            job.get("basic_qualifications"),
            job.get("preferred_qualifications"),
        )
        if isinstance(part, str) and part.strip()
    )
    return RawJob(
        job_url=job_url,
        title=str(job.get("title") or "").strip() or None,
        company=str(job.get("company_name") or "Amazon").strip() or "Amazon",
        description=description or None,
        location=location,
        site="amazon",
        date_posted=_parse_date(job.get("posted_date")),
    )


async def _fetch_page(client: httpx.AsyncClient, query: SearchQuery, offset: int) -> dict:
    response = await client.get(_search_url(query, offset), timeout=30)
    response.raise_for_status()
    return response.json()


async def _fetch_jobs(client: httpx.AsyncClient, query: SearchQuery, config: ScraperConfig) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()
    offset = 0
    max_pages = max(3, min(20, (config.max_results_per_query // _AMAZON_PAGE_SIZE) + 2))

    for _ in range(max_pages):
        payload = await _fetch_page(client, query, offset)
        page_jobs = payload.get("jobs") or []
        if not page_jobs:
            break

        for item in page_jobs:
            if not isinstance(item, dict):
                continue
            if not _matches_query(item, query):
                continue
            job = _normalize_job(item)
            if job is None or job.job_url in seen_urls:
                continue
            seen_urls.add(job.job_url)
            jobs.append(job)
            if len(jobs) >= config.max_results_per_query:
                break

        if len(page_jobs) < _AMAZON_PAGE_SIZE:
            break
        offset += _AMAZON_PAGE_SIZE
        await asyncio.sleep(0.1)

    return jobs


async def search(
    queries: list[SearchQuery],
    config: ScraperConfig,
    db: AsyncSession | None = None,
) -> list[RawJob]:
    if not queries:
        return []

    all_jobs: list[RawJob] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        for query in queries:
            cache_query = _cache_query(query, config)
            cached = await load_cached_jobs(db, provider="amazon_jobs", site="amazon", query=cache_query, config=config)
            if cached is not None:
                all_jobs.extend(cached)
                continue
            try:
                jobs = await _fetch_jobs(client, query, config)
                await store_cached_jobs(db, provider="amazon_jobs", site="amazon", query=cache_query, config=config, jobs=jobs)
                all_jobs.extend(jobs)
            except Exception:
                logger.exception("Amazon Jobs failed for %s / %s", query.term, query.location)
            await asyncio.sleep(0.2)
    return all_jobs
