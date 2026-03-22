from __future__ import annotations

import logging
from datetime import datetime

import httpx

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)


def _parse_date(val) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _fetch_himalayas(client: httpx.AsyncClient, query: SearchQuery) -> list[RawJob]:
    try:
        resp = await client.get("https://himalayas.app/jobs/api", params={"limit": "50"}, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("jobs", [])
    except Exception:
        logger.exception("Himalayas API failed")
        return []

    term_lower = query.term.lower()
    jobs = []
    for item in items:
        title = item.get("title", "")
        if term_lower not in title.lower() and term_lower not in (item.get("category_name") or "").lower():
            continue
        url = item.get("applicationLink") or f"https://himalayas.app/jobs/{item.get('slug', '')}"
        jobs.append(RawJob(
            job_url=url, title=title, company=item.get("companyName"),
            description=item.get("description"), location=item.get("location") or "Remote",
            site="himalayas", date_posted=_parse_date(item.get("pubDate")),
        ))
    return jobs


async def _fetch_remotive(client: httpx.AsyncClient, query: SearchQuery) -> list[RawJob]:
    try:
        resp = await client.get("https://remotive.com/api/remote-jobs", params={"search": query.term, "limit": "50"}, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("jobs", [])
    except Exception:
        logger.exception("Remotive API failed")
        return []

    jobs = []
    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        jobs.append(RawJob(
            job_url=url, title=item.get("title"), company=item.get("company_name"),
            description=item.get("description"),
            location=item.get("candidate_required_location") or "Remote",
            site="remotive", date_posted=_parse_date(item.get("publication_date")),
        ))
    return jobs


async def _fetch_jobicy(client: httpx.AsyncClient, query: SearchQuery) -> list[RawJob]:
    try:
        resp = await client.get("https://jobicy.com/api/v2/remote-jobs", params={"count": "50", "tag": query.term}, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("jobs", [])
    except Exception:
        logger.exception("Jobicy API failed")
        return []

    jobs = []
    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        jobs.append(RawJob(
            job_url=url, title=item.get("jobTitle"), company=item.get("companyName"),
            description=item.get("jobDescription"), location=item.get("jobGeo") or "Remote",
            site="jobicy", date_posted=_parse_date(item.get("pubDate")),
        ))
    return jobs


async def search(queries: list[SearchQuery], config: ScraperConfig) -> list[RawJob]:
    all_jobs: list[RawJob] = []
    async with httpx.AsyncClient() as client:
        for query in queries[:5]:
            for fetcher in [_fetch_himalayas, _fetch_remotive, _fetch_jobicy]:
                try:
                    results = await fetcher(client, query)
                    all_jobs.extend(results)
                except Exception:
                    logger.exception("Free API fetcher failed")
    return all_jobs
