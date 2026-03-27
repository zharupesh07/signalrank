from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source registry — verified working as of 2026-03-26
#
# Non-redundancy strategy: queries are round-robin partitioned so each query
# goes to exactly ONE source. No duplicate (query, source) pairs → no wasted
# quota and no duplicate results from the same search.
#
# Each source covers a different slice:
#   jsearch          — Google Jobs aggregator (LinkedIn+Indeed+Glassdoor), 1 week
#   indeed           — Indeed only, full lookback window
#   li_jobsearch     — LinkedIn curated feed, last 24h, title+location filter
#   li_7d            — LinkedIn curated feed, last 7 days (broader window)
#   jobs_scanner     — LinkedIn scraper, location-specific POST search
#   li_bulk          — LinkedIn bulk scraper, 25 results/call, India geo
# ---------------------------------------------------------------------------

SOURCES = {
    "jsearch": {
        "host": "jsearch.p.rapidapi.com",
        "path": "/search",
        "method": "GET",
        "role": "Google Jobs aggregator — LinkedIn+Indeed+Glassdoor, last week",
        "params_fn": lambda q, cfg: {
            "query": f"{q.term} in {q.location}" if q.location else q.term,
            "num_pages": "1",
            "date_posted": "week",
        },
    },
    "indeed": {
        "host": "indeed12.p.rapidapi.com",
        "path": "/jobs/search",
        "method": "GET",
        "role": "Indeed — location-aware, 7-day window",
        "params_fn": lambda q, cfg: {
            "query": q.term,
            "location": q.location or cfg.default_country,
            "fromage": "7",
            "start": "1",
        },
    },
    "li_jobsearch": {
        "host": "linkedin-job-search-api.p.rapidapi.com",
        "path": "/active-jb-24h",
        "method": "GET",
        "role": "LinkedIn curated — last 24h, title+location filtered",
        "params_fn": lambda q, cfg: {
            "title_filter": q.term,
            "location_filter": q.location or cfg.default_country,
            "limit": "100",
        },
    },
    "li_7d": {
        "host": "linkedin-jobs-api2.p.rapidapi.com",
        "path": "/active-jb-7d",
        "method": "GET",
        "role": "LinkedIn curated — last 7 days, broader window",
        "params_fn": lambda q, cfg: {
            "title_filter": q.term,
            "location_filter": q.location or cfg.default_country,
            "limit": "100",
        },
    },
    "jobs_scanner": {
        "host": "linkedin-jobs-search.p.rapidapi.com",
        "path": "/",
        "method": "POST",
        "role": "LinkedIn scraper — location-specific POST, 100 req/mo free",
        "params_fn": lambda q, cfg: {
            "search_terms": q.term,
            "location": q.location or cfg.default_country,
            "page": "1",
        },
    },
    "li_bulk": {
        "host": "linkedin-bulk-data-scraper.p.rapidapi.com",
        "path": "/search_jobs",
        "method": "GET",
        "role": "LinkedIn bulk — different index, India geo, 25 results/call",
        "params_fn": lambda q, cfg: {
            "query": q.term,
            "location": q.location or cfg.default_country,
            "page": "1",
        },
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
    items: list = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # li_bulk wraps in response.jobs
        if "response" in data and isinstance(data["response"], dict):
            data = data["response"]
        for key in ("data", "results", "jobs", "hits", "job_list"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        if not isinstance(item, dict):
            continue

        # li_bulk nests job data under "data" key
        job_data = item.get("data", item)

        url = (
            job_data.get("job_url")
            or job_data.get("url")
            or job_data.get("external_apply_url")
            or job_data.get("jobPostingUrl")
            or job_data.get("job_apply_link")
            or job_data.get("redirect_url")
            or job_data.get("linkedin_job_url_cleaned")
            or job_data.get("link")
            or ""
        )
        if not url:
            continue

        location = (
            job_data.get("location")
            or job_data.get("formattedLocation")
            or job_data.get("job_location")
            or job_data.get("job_city")
            or job_data.get("job_country")
        )
        # li_jobsearch / li_7d store location in locations_raw list
        if not location:
            locs = job_data.get("locations_raw") or []
            if locs and isinstance(locs[0], dict):
                location = locs[0].get("address", {}).get("addressLocality") or locs[0].get("name")

        jobs.append(RawJob(
            job_url=url,
            title=(
                job_data.get("title")
                or job_data.get("job_title")
                or job_data.get("job_position")
                or job_data.get("name")
            ),
            company=(
                job_data.get("company")
                or job_data.get("organization")
                or job_data.get("company_name")
                or job_data.get("companyName")
                or job_data.get("employer_name")
            ),
            description=(
                job_data.get("description")
                or job_data.get("job_description")
                or job_data.get("snippet")
                or job_data.get("text")
            ),
            location=location,
            site=source_name,
            date_posted=_parse_date(
                job_data.get("date_posted")
                or job_data.get("posted_date")
                or job_data.get("job_posted_at_datetime_utc")
                or job_data.get("posted_at")
                or job_data.get("list_date")
            ),
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
    method = src.get("method", "GET")

    async with sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                if method == "POST":
                    headers["Content-Type"] = "application/json"
                    resp = await client.post(
                        f"https://{src['host']}{src['path']}",
                        json=params,
                        headers=headers,
                        timeout=30,
                    )
                else:
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
                if resp.status_code in (401, 403):
                    logger.warning(
                        "%s returned %d — not subscribed or quota exceeded, skipping",
                        source_name, resp.status_code,
                    )
                    return []
                resp.raise_for_status()
                return _normalize_results(source_name, resp.json())
            except Exception:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    logger.exception("RapidAPI %s failed for query '%s'", source_name, query.term)
        return []


def _partition_queries(
    queries: list[SearchQuery],
    source_names: list[str],
) -> list[tuple[str, SearchQuery]]:
    """Round-robin assign each query to exactly one source.

    Guarantees no two sources receive the same query, preventing duplicate
    results and preserving free-tier quota across all APIs.
    """
    return [(source_names[i % len(source_names)], q) for i, q in enumerate(queries)]


async def search(queries: list[SearchQuery], config: ScraperConfig) -> list[RawJob]:
    if not config.rapidapi_key:
        logger.info("RAPIDAPI_KEY not set, skipping RapidAPI sources")
        return []

    source_names = list(SOURCES.keys())
    assignments = _partition_queries(queries, source_names)

    logger.info(
        "RapidAPI: %d queries → %d sources (round-robin): %s",
        len(queries), len(source_names), source_names,
    )

    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    all_jobs: list[RawJob] = []

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_source(client, src_name, query, config, sem)
            for src_name, query in assignments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (src_name, query), r in zip(assignments, results):
            if isinstance(r, list):
                all_jobs.extend(r)
                logger.info("  %s [%s @ %s]: %d jobs", src_name, query.term, query.location, len(r))
            elif isinstance(r, Exception):
                logger.warning("  %s [%s] error: %s", src_name, query.term, r)

    return all_jobs
