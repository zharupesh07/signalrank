from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

SOURCES = {
    "linkedin": {
        "host": "linkedin-data-api.p.rapidapi.com",
        "path": "/search-jobs",
        "params_fn": lambda q, cfg: {
            "keywords": q.term,
            "locationId": "",
            "datePosted": "past24Hours",
            "sort": "mostRecent",
        },
    },
    "jsearch": {
        "host": "jsearch.p.rapidapi.com",
        "path": "/search",
        "params_fn": lambda q, cfg: {
            "query": f"{q.term} in {q.location}",
            "num_pages": "1",
            "date_posted": "week",
        },
    },
    "indeed": {
        "host": "indeed12.p.rapidapi.com",
        "path": "/jobs/search",
        "params_fn": lambda q, cfg: {
            "query": q.term,
            "location": q.location,
            "fromage": str(cfg.hours_old // 24),
            "start": "1",
        },
    },
    "google": {
        "host": "google-jobs-api.p.rapidapi.com",
        "path": "/api/google-jobs",
        "params_fn": lambda q, cfg: {
            "query": f"{q.term} {q.location}",
        },
    },
    "arbeitnow": {
        "host": "arbeitnow-free-job-board.p.rapidapi.com",
        "path": "/api/job-board-api",
        "params_fn": lambda q, cfg: {},
    },
}

MAX_RETRIES = 2
SEMAPHORE_LIMIT = 4


def _parse_date(val) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _normalize_results(source_name: str, data) -> list[RawJob]:
    jobs = []
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("data", "results", "jobs", "hits"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        if not isinstance(item, dict):
            continue
        url = (
            item.get("job_url") or item.get("url") or item.get("link")
            or item.get("job_apply_link") or item.get("redirect_url") or ""
        )
        if not url:
            continue
        jobs.append(RawJob(
            job_url=url,
            title=item.get("title") or item.get("job_title"),
            company=item.get("company") or item.get("company_name") or item.get("employer_name"),
            description=item.get("description") or item.get("job_description") or item.get("snippet"),
            location=item.get("location") or item.get("job_city") or item.get("job_country"),
            site=source_name,
            date_posted=_parse_date(item.get("date_posted") or item.get("job_posted_at_datetime_utc")),
        ))
    return jobs


async def _fetch_source(
    client: httpx.AsyncClient,
    source_name: str,
    query: SearchQuery,
    config: ScraperConfig,
    sem: asyncio.Semaphore,
) -> list[RawJob]:
    src = SOURCES[source_name]
    params = src["params_fn"](query, config)
    headers = {
        "x-rapidapi-key": config.rapidapi_key,
        "x-rapidapi-host": src["host"],
    }

    async with sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await client.get(
                    f"https://{src['host']}{src['path']}",
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", str(2 * (attempt + 1))))
                    logger.warning("%s 429, retrying after %.1fs", source_name, retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return _normalize_results(source_name, resp.json())
            except Exception:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    logger.exception("RapidAPI %s failed for query %s", source_name, query.term)
        return []


async def search(queries: list[SearchQuery], config: ScraperConfig) -> list[RawJob]:
    if not config.rapidapi_key:
        logger.info("RAPIDAPI_KEY not set, skipping Phase 1")
        return []

    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    all_jobs: list[RawJob] = []

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_source(client, src_name, query, config, sem)
            for query in queries
            for src_name in SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_jobs.extend(r)
            elif isinstance(r, Exception):
                logger.warning("RapidAPI task failed: %s", r)

    return all_jobs
