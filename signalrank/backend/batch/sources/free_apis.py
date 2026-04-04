from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
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
        resp = await client.get("https://himalayas.app/jobs/api", params={"limit": "500"}, timeout=30)
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
        resp = await client.get("https://remotive.com/api/remote-jobs", params={"search": query.term, "limit": "500"}, timeout=30)
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
        resp = await client.get("https://jobicy.com/api/v2/remote-jobs", params={"count": "100", "tag": query.term}, timeout=30)
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


async def search(queries: list[SearchQuery], config: ScraperConfig, db: AsyncSession | None = None) -> list[RawJob]:
    # Deduplicate by term — location is irrelevant for these remote-job APIs
    seen_terms: set[str] = set()
    unique_queries: list[SearchQuery] = []
    for q in queries:
        key = q.term.lower()
        if key not in seen_terms:
            seen_terms.add(key)
            unique_queries.append(q)

    all_jobs: list[RawJob] = []
    async with httpx.AsyncClient() as client:
        # Himalayas returns the same feed regardless of query — fetch once
        try:
            query = unique_queries[0] if unique_queries else queries[0]
            cached = await load_cached_jobs(db, provider="free_apis", site="himalayas", query=query, config=config)
            if cached is None:
                himalayas_jobs = await _fetch_himalayas(client, query)
                await store_cached_jobs(db, provider="free_apis", site="himalayas", query=query, config=config, jobs=himalayas_jobs)
            else:
                himalayas_jobs = cached
            all_jobs.extend(himalayas_jobs)
        except Exception:
            logger.exception("Free API fetcher failed for himalayas")

        # Remotive and Jobicy filter by search term — call once per unique term
        for query in unique_queries:
            for fetcher in [_fetch_remotive, _fetch_jobicy]:
                try:
                    site = "remotive" if fetcher is _fetch_remotive else "jobicy"
                    cached = await load_cached_jobs(db, provider="free_apis", site=site, query=query, config=config)
                    if cached is None:
                        results = await fetcher(client, query)
                        await store_cached_jobs(db, provider="free_apis", site=site, query=query, config=config, jobs=results)
                    else:
                        results = cached
                    all_jobs.extend(results)
                except Exception:
                    logger.exception("Free API fetcher failed")
                await asyncio.sleep(1.0)  # avoid hammering free APIs back-to-back
    return all_jobs
