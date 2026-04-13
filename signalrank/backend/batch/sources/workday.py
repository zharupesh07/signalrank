from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

_QUERY_STOPWORDS = {
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

_WORKDAY_COMPANIES = [
    {
        "company": "Aptiv",
        "slug": "aptiv",
        "host": "aptiv.wd5.myworkdayjobs.com",
        "tenant": "aptiv",
        "site": "APTIV_CAREERS",
        "base_url": "https://aptiv.wd5.myworkdayjobs.com/APTIV_CAREERS",
    },
    {
        "company": "Western Union",
        "slug": "western_union",
        "host": "westernunion.wd5.myworkdayjobs.com",
        "tenant": "westernunion",
        "site": "WesternUnionJobs",
        "base_url": "https://westernunion.wd5.myworkdayjobs.com/WesternUnionJobs",
    },
    {
        "company": "Target",
        "slug": "target",
        "host": "target.wd5.myworkdayjobs.com",
        "tenant": "target",
        "site": "targetcareers",
        "base_url": "https://target.wd5.myworkdayjobs.com/targetcareers",
    },
    {
        "company": "Philips",
        "slug": "philips",
        "host": "philips.wd3.myworkdayjobs.com",
        "tenant": "philips",
        "site": "jobs-and-careers",
        "base_url": "https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers",
    },
    {
        "company": "Maersk",
        "slug": "maersk",
        "host": "maersk.wd3.myworkdayjobs.com",
        "tenant": "maersk",
        "site": "Maersk_Careers",
        "base_url": "https://maersk.wd3.myworkdayjobs.com/en-US/Maersk_Careers",
    },
    {
        "company": "Eli Lilly and Company",
        "slug": "eli_lilly",
        "host": "lilly.wd5.myworkdayjobs.com",
        "tenant": "lilly",
        "site": "LLY",
        "base_url": "https://lilly.wd5.myworkdayjobs.com/en-US/LLY",
    },
    {
        "company": "HP",
        "slug": "hp",
        "host": "hp.wd5.myworkdayjobs.com",
        "tenant": "hp",
        "site": "ExternalCareerSite",
        "base_url": "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite",
    },
    {
        "company": "Expedia Group",
        "slug": "expedia_group",
        "host": "expedia.wd108.myworkdayjobs.com",
        "tenant": "expedia",
        "site": "search",
        "base_url": "https://expedia.wd108.myworkdayjobs.com/en-US/search",
    },
    {
        "company": "Dell Technologies",
        "slug": "dell_technologies",
        "host": "dell.wd1.myworkdayjobs.com",
        "tenant": "dell",
        "site": "External",
        "base_url": "https://dell.wd1.myworkdayjobs.com/External",
    },
    {
        "company": "Cardinal Health",
        "slug": "cardinal_health",
        "host": "cardinalhealth.wd1.myworkdayjobs.com",
        "tenant": "cardinalhealth",
        "site": "EXT",
        "base_url": "https://cardinalhealth.wd1.myworkdayjobs.com/en-US/EXT",
    },
    {
        "company": "Fractal Analytics",
        "slug": "fractal_analytics",
        "host": "fractal.wd1.myworkdayjobs.com",
        "tenant": "fractal",
        "site": "Careers",
        "base_url": "https://fractal.wd1.myworkdayjobs.com/Careers",
    },
    {
        "company": "Salesforce",
        "slug": "salesforce",
        "host": "salesforce.wd12.myworkdayjobs.com",
        "tenant": "salesforce",
        "site": "External_Career_Site",
        "base_url": "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site",
    },
    {
        "company": "GE HealthCare",
        "slug": "ge_healthcare",
        "host": "gehc.wd5.myworkdayjobs.com",
        "tenant": "gehc",
        "site": "GEHC_ExternalSite",
        "base_url": "https://gehc.wd5.myworkdayjobs.com/en-US/GEHC_ExternalSite",
    },
    {
        "company": "Autodesk",
        "slug": "autodesk",
        "host": "autodesk.wd1.myworkdayjobs.com",
        "tenant": "autodesk",
        "site": "Ext",
        "base_url": "https://autodesk.wd1.myworkdayjobs.com/Ext",
    },
    {
        "company": "Adobe",
        "slug": "adobe",
        "host": "adobe.wd5.myworkdayjobs.com",
        "tenant": "adobe",
        "site": "external_experienced",
        "base_url": "https://adobe.wd5.myworkdayjobs.com/external_experienced",
    },
    {
        "company": "BrowserStack",
        "slug": "browserstack",
        "host": "browserstack.wd3.myworkdayjobs.com",
        "tenant": "browserstack",
        "site": "External",
        "base_url": "https://browserstack.wd3.myworkdayjobs.com/External",
    },
    {
        "company": "FIS",
        "slug": "fis",
        "host": "fis.wd5.myworkdayjobs.com",
        "tenant": "fis",
        "site": "SearchJobs",
        "base_url": "https://fis.wd5.myworkdayjobs.com/SearchJobs",
    },
    {
        "company": "Mastercard",
        "slug": "mastercard",
        "host": "mastercard.wd1.myworkdayjobs.com",
        "tenant": "mastercard",
        "site": "CorporateCareers",
        "base_url": "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers",
    },
    {
        "company": "Barclays",
        "slug": "barclays",
        "host": "barclays.wd3.myworkdayjobs.com",
        "tenant": "barclays",
        "site": "External_Career_Site_Barclays",
        "base_url": "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays",
    },
    {
        "company": "Priceline",
        "slug": "priceline",
        "host": "priceline.wd1.myworkdayjobs.com",
        "tenant": "priceline",
        "site": "Priceline",
        "base_url": "https://priceline.wd1.myworkdayjobs.com/en-US/Priceline",
    },
    {
        "company": "Walmart",
        "slug": "walmart",
        "host": "walmart.wd5.myworkdayjobs.com",
        "tenant": "walmart",
        "site": "WalmartExternal",
        "base_url": "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal",
    },
    {
        "company": "GE Vernova",
        "slug": "ge_vernova",
        "host": "gevernova.wd5.myworkdayjobs.com",
        "tenant": "gevernova",
        "site": "Vernova_ExternalSite",
        "base_url": "https://gevernova.wd5.myworkdayjobs.com/Vernova_ExternalSite",
    },
    {
        "company": "Ciena",
        "slug": "ciena",
        "host": "ciena.wd5.myworkdayjobs.com",
        "tenant": "ciena",
        "site": "Careers",
        "base_url": "https://ciena.wd5.myworkdayjobs.com/Careers",
    },
]


def active_companies() -> list[dict]:
    return list(_WORKDAY_COMPANIES)


def _cache_query(company: dict, query: SearchQuery, config: ScraperConfig) -> SearchQuery:
    return SearchQuery(
        term=query.term,
        location=query.location,
        country=query.country or config.default_country,
    )


def _list_url(company: dict) -> str:
    return f"https://{company['host']}/wday/cxs/{company['tenant']}/{company['site']}/jobs"


def _detail_url(company: dict, slug: str) -> str:
    return f"https://{company['host']}/wday/cxs/{company['tenant']}/{company['site']}/job/{slug}"


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _query_tokens(term: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9\+#/]+", str(term or "").lower())
    filtered = [token for token in tokens if token not in _QUERY_STOPWORDS]
    return filtered or tokens


def _matches_location(query: SearchQuery, text: str | None) -> bool:
    if not query.location:
        return True
    location = str(text or "").lower()
    query_loc = query.location.lower()
    return query_loc in location or ("remote" in location and query_loc in {"remote", ""})


def _matches_query(summary: dict, detail: dict, query: SearchQuery) -> bool:
    title = str(summary.get("title") or detail.get("title") or "")
    description = str(detail.get("jobDescription") or "")
    combined = f"{title} {description}".lower()
    raw_term = str(query.term or "").lower().strip()
    location_text = " ".join(
        str(item or "")
        for item in (
            summary.get("locationsText"),
            (detail.get("jobRequisitionLocation") or {}).get("descriptor"),
            detail.get("remoteType"),
        )
        if item
    )

    if raw_term and raw_term in combined:
        return _matches_location(query, location_text)

    tokens = _query_tokens(query.term)
    if not tokens:
        return False
    overlap = sum(1 for token in tokens if token in combined)
    needed = min(2, len(tokens))
    if overlap < needed:
        return False
    return _matches_location(query, location_text)


async def _fetch_query_page(
    client: httpx.AsyncClient,
    company: dict,
    query: SearchQuery,
    *,
    limit: int,
    offset: int,
) -> dict:
    response = await client.post(
        _list_url(company),
        json={
            "limit": limit,
            "offset": offset,
            "searchText": query.term,
        },
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def _fetch_job_detail(client: httpx.AsyncClient, company: dict, slug: str) -> dict:
    response = await client.get(_detail_url(company, slug), timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload.get("jobPostingInfo") or {}


def _normalize_job(company: dict, summary: dict, detail: dict) -> RawJob | None:
    job_url = str(detail.get("externalUrl") or "").strip()
    if not job_url:
        external_path = str(summary.get("externalPath") or "").strip()
        if not external_path:
            return None
        job_url = f"{company['base_url'].rstrip('/')}{external_path}"

    location = (detail.get("jobRequisitionLocation") or {}).get("descriptor") or summary.get("locationsText")
    return RawJob(
        job_url=job_url,
        title=detail.get("title") or summary.get("title"),
        company=company["company"],
        description=detail.get("jobDescription") or "",
        location=location,
        site="workday",
        date_posted=_parse_date(detail.get("postedOn")),
    )


async def _fetch_company_jobs(
    client: httpx.AsyncClient,
    company: dict,
    query: SearchQuery,
    config: ScraperConfig,
) -> list[RawJob]:
    page_size = min(100, max(20, config.max_results_per_query))
    offset = 0
    total = None
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    while total is None or offset < min(total, config.max_results_per_query):
        payload = await _fetch_query_page(client, company, query, limit=page_size, offset=offset)
        if total is None:
            total = int(payload.get("total") or 0)
        postings = payload.get("jobPostings") or []
        if not postings:
            break

        for posting in postings:
            external_path = str(posting.get("externalPath") or "").strip()
            slug = external_path.split("/")[-1] if external_path else ""
            if not slug:
                continue
            detail = await _fetch_job_detail(client, company, slug)
            if not detail or not _matches_query(posting, detail, query):
                continue
            job = _normalize_job(company, posting, detail)
            if job is None or job.job_url in seen_urls:
                continue
            seen_urls.add(job.job_url)
            jobs.append(job)

        offset += page_size
        if len(postings) < page_size:
            break
        await asyncio.sleep(0.1)

    return jobs


async def probe_company(client: httpx.AsyncClient, company: dict) -> dict[str, str | int]:
    try:
        response = await client.post(
            _list_url(company),
            json={"limit": 1, "offset": 0, "searchText": ""},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "company": company["company"],
            "slug": company["slug"],
            "status": response.status_code,
            "total": int(payload.get("total") or 0),
            "url": _list_url(company),
        }
    except Exception:
        return {
            "company": company["company"],
            "slug": company["slug"],
            "status": type(exc).__name__,
            "url": _list_url(company),
        }


async def search(
    queries: list[SearchQuery],
    config: ScraperConfig,
    db: AsyncSession | None = None,
) -> list[RawJob]:
    if not queries:
        return []

    all_jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        for company in active_companies():
            for query in queries:
                cache_query = _cache_query(company, query, config)
                try:
                    cached = await load_cached_jobs(
                        db,
                        provider="workday",
                        site=company["slug"],
                        query=cache_query,
                        config=config,
                    )
                    if cached is None:
                        jobs = await _fetch_company_jobs(client, company, query, config)
                        await store_cached_jobs(
                            db,
                            provider="workday",
                            site=company["slug"],
                            query=cache_query,
                            config=config,
                            jobs=jobs,
                        )
                    else:
                        jobs = cached
                except Exception:
                    logger.exception("Workday fetch failed for %s (%s)", company["company"], query.term)
                    jobs = []

                for job in jobs:
                    if job.job_url in seen_urls:
                        continue
                    seen_urls.add(job.job_url)
                    all_jobs.append(job)
                await asyncio.sleep(0.1)

    return all_jobs
