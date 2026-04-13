from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

_BASE_URL = "https://swiggy.mynexthire.com/employer"
_CAREERS_URL = f"{_BASE_URL}/jobs/careers"


def _cache_query(config: ScraperConfig) -> SearchQuery:
    return SearchQuery(term="swiggy:board", location="", country=config.default_country)


def _query_tokens(term: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9\+#/]+", str(term or "").lower())
    stopwords = {
        "engineer",
        "developer",
        "specialist",
        "architect",
        "manager",
        "lead",
        "senior",
        "staff",
        "principal",
        "remote",
    }
    filtered = [token for token in tokens if token not in stopwords]
    return filtered or tokens


def _matches_location(query: SearchQuery, text: str | None) -> bool:
    if not query.location:
        return True
    location = str(text or "").lower()
    qloc = query.location.lower()
    return qloc in location or ("remote" in location and qloc in {"remote", ""})


def _matches_query(job: dict, query: SearchQuery) -> bool:
    title = str(job.get("reqTitle") or job.get("designation") or "")
    description = str(job.get("jdDisplay") or "")
    combined = f"{title} {description} {job.get('buName') or ''}".lower()
    raw_term = str(query.term or "").lower().strip()
    location_text = " ".join(
        str(part or "")
        for part in (
            job.get("location"),
            job.get("locationAddress"),
            job.get("buName"),
        )
    )
    if raw_term and raw_term in combined:
        return _matches_location(query, location_text)

    tokens = _query_tokens(query.term)
    if not tokens:
        return True
    overlap = sum(1 for token in tokens if token in combined)
    if overlap < min(2, len(tokens)):
        return False
    return _matches_location(query, location_text)


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _job_url(req_id: int) -> str:
    payload = {
        "pageType": "jd",
        "cvSource": "careers",
        "reqId": req_id,
        "requester": {"id": "", "code": "", "name": ""},
        "page": "careers",
        "bufilter": -1,
        "customFields": {},
    }
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return f"{_CAREERS_URL}?src=careers&p={encoded}"


async def _fetch_requisition_list(client: httpx.AsyncClient) -> list[dict]:
    response = await client.post(
        f"{_BASE_URL}/careers/reqlist/get",
        json={"source": "careers", "code": "careers", "filterByBuId": ""},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("reqDetailsBOList") or []


def _normalize_job(job: dict) -> RawJob | None:
    req_id = job.get("reqId")
    if req_id is None:
        return None
    return RawJob(
        job_url=_job_url(int(req_id)),
        title=str(job.get("designation") or job.get("reqTitle") or "").strip() or None,
        company="Swiggy",
        description=str(job.get("jdDisplay") or "").strip() or None,
        location=str(job.get("locationAddress") or job.get("location") or "").strip() or None,
        site="mynexthire",
        date_posted=_parse_date(job.get("approvedOn")),
    )


async def _fetch_jobs(client: httpx.AsyncClient, query: SearchQuery, config: ScraperConfig) -> list[RawJob]:
    requisitions = await _fetch_requisition_list(client)
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()
    limit = config.max_results_per_query if str(query.term or "").strip() else 500
    for item in requisitions:
        if not isinstance(item, dict):
            continue
        if not _matches_query(item, query):
            continue
        job = _normalize_job(item)
        if job is None or job.job_url in seen_urls:
            continue
        seen_urls.add(job.job_url)
        jobs.append(job)
        if len(jobs) >= limit:
            break
    return jobs


async def search(
    queries: list[SearchQuery],
    config: ScraperConfig,
    db: AsyncSession | None = None,
) -> list[RawJob]:
    if not queries:
        return []

    cache_query = _cache_query(config)
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        cached = await load_cached_jobs(db, provider="swiggy", site="swiggy", query=cache_query, config=config)
        if cached is None:
            try:
                all_board_jobs = await _fetch_jobs(client, SearchQuery(term="", location="", country=config.default_country), config)
                await store_cached_jobs(db, provider="swiggy", site="swiggy", query=cache_query, config=config, jobs=all_board_jobs)
            except Exception:
                logger.exception("Swiggy fetch failed")
                return []
        else:
            all_board_jobs = cached

    results: list[RawJob] = []
    seen_urls: set[str] = set()
    for query in queries:
        for job in all_board_jobs:
            if job.job_url in seen_urls:
                continue
            if _matches_query(
                {
                    "reqTitle": job.title,
                    "jdDisplay": job.description,
                    "location": job.location,
                    "locationAddress": job.location,
                    "buName": job.company,
                },
                query,
            ):
                seen_urls.add(job.job_url)
                results.append(job)
        await asyncio.sleep(0.2)
    return results
