from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig
from domain.company import _norm

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

_DISABLED_ATS_COMPANIES = {
    "Ada": "greenhouse 404 on 2026-04-12",
    "Factorial": "greenhouse 404 on 2026-04-12",
    "Runway": "greenhouse 404 on 2026-04-12",
    "Tinybird": "ashby 404 on 2026-04-12",
    "Travelperk": "ashby 404 on 2026-04-12",
    "Weights & Biases": "lever 404 on 2026-04-12",
    "Forto": "lever 404 on 2026-04-12",
    "Vinted": "lever 404 on 2026-04-12",
}

_ATS_COMPANIES = [
    {"company": "Databricks", "site": "greenhouse", "slug": "databricks"},
    {"company": "GitLab", "site": "greenhouse", "slug": "gitlab"},
    {"company": "PolyAI", "site": "greenhouse", "slug": "polyai"},
    {"company": "Parloa", "site": "greenhouse", "slug": "parloa"},
    {"company": "Intercom", "site": "greenhouse", "slug": "intercom"},
    {"company": "Hume AI", "site": "greenhouse", "slug": "humeai"},
    {"company": "Airtable", "site": "greenhouse", "slug": "airtable"},
    {"company": "Temporal", "site": "greenhouse", "slug": "temporal"},
    {"company": "Ada", "site": "greenhouse", "slug": "ada"},
    {"company": "Speechmatics", "site": "greenhouse", "slug": "speechmatics"},
    {"company": "Factorial", "site": "greenhouse", "slug": "factorial"},
    {"company": "Black Forest Labs", "site": "greenhouse", "slug": "blackforestlabs"},
    {"company": "Helsing", "site": "greenhouse", "slug": "helsing"},
    {"company": "Celonis", "site": "greenhouse", "slug": "celonis"},
    {"company": "Contentful", "site": "greenhouse", "slug": "contentful"},
    {"company": "GetYourGuide", "site": "greenhouse", "slug": "getyourguide"},
    {"company": "HelloFresh", "site": "greenhouse", "slug": "hellofresh"},
    {"company": "N26", "site": "greenhouse", "slug": "n26"},
    {"company": "Trade Republic", "site": "greenhouse", "slug": "traderepublicbank"},
    {"company": "SumUp", "site": "greenhouse", "slug": "sumup"},
    {"company": "Scandit", "site": "greenhouse", "slug": "scandit"},
    {"company": "Wayve", "site": "greenhouse", "slug": "wayve"},
    {"company": "Isomorphic Labs", "site": "greenhouse", "slug": "isomorphiclabs"},
    {"company": "PhysicsX", "site": "greenhouse", "slug": "physicsx"},
    {"company": "Stability AI", "site": "greenhouse", "slug": "stabilityai"},
    {"company": "Amplemarket", "site": "greenhouse", "slug": "amplemarket"},
    {"company": "Runway", "site": "greenhouse", "slug": "runwayml"},
    {"company": "Hightouch", "site": "greenhouse", "slug": "hightouch"},
    {"company": "PlanetScale", "site": "greenhouse", "slug": "planetscale"},
    {"company": "ElevenLabs", "site": "ashby", "slug": "elevenlabs"},
    {"company": "Deepgram", "site": "ashby", "slug": "deepgram"},
    {"company": "Snowflake", "site": "ashby", "slug": "snowflake"},
    {"company": "Vapi", "site": "ashby", "slug": "vapi"},
    {"company": "Bland AI", "site": "ashby", "slug": "bland"},
    {"company": "Sierra", "site": "ashby", "slug": "sierra"},
    {"company": "Decagon", "site": "ashby", "slug": "decagon"},
    {"company": "Lindy", "site": "ashby", "slug": "lindy"},
    {"company": "n8n", "site": "ashby", "slug": "n8n"},
    {"company": "Zapier", "site": "ashby", "slug": "zapier"},
    {"company": "Cohere", "site": "ashby", "slug": "cohere"},
    {"company": "Attio", "site": "ashby", "slug": "attio"},
    {"company": "Tinybird", "site": "ashby", "slug": "tinybird"},
    {"company": "Travelperk", "site": "ashby", "slug": "travelperk"},
    {"company": "Aleph Alpha", "site": "ashby", "slug": "AlephAlpha"},
    {"company": "DeepL", "site": "ashby", "slug": "DeepL"},
    {"company": "Lakera", "site": "ashby", "slug": "lakera.ai"},
    {"company": "Cradle", "site": "ashby", "slug": "cradlebio"},
    {"company": "Photoroom", "site": "ashby", "slug": "photoroom"},
    {"company": "Synthesia", "site": "ashby", "slug": "synthesia"},
    {"company": "Faculty", "site": "ashby", "slug": "faculty"},
    {"company": "Causaly", "site": "ashby", "slug": "causaly"},
    {"company": "Lovable", "site": "ashby", "slug": "lovable"},
    {"company": "Legora", "site": "ashby", "slug": "legora"},
    {"company": "Perplexity", "site": "ashby", "slug": "perplexity"},
    {"company": "Clay Labs", "site": "ashby", "slug": "claylabs"},
    {"company": "WorkOS", "site": "ashby", "slug": "workos"},
    {"company": "Supabase", "site": "ashby", "slug": "supabase"},
    {"company": "Resend", "site": "ashby", "slug": "resend"},
    {"company": "Clerk", "site": "ashby", "slug": "clerk"},
    {"company": "Inngest", "site": "ashby", "slug": "inngest"},
    {"company": "Mistral AI", "site": "lever", "slug": "mistral"},
    {"company": "Weights & Biases", "site": "lever", "slug": "wandb"},
    {"company": "Atlassian", "site": "lever", "slug": "atlassian"},
    {"company": "Palantir", "site": "lever", "slug": "palantir"},
    {"company": "Clarity AI", "site": "lever", "slug": "clarity-ai"},
    {"company": "Qonto", "site": "lever", "slug": "qonto"},
    {"company": "Forto", "site": "lever", "slug": "forto"},
    {"company": "Pigment", "site": "lever", "slug": "pigment"},
    {"company": "Spotify", "site": "lever", "slug": "spotify"},
    {"company": "Vinted", "site": "lever", "slug": "vinted"},
    {"company": "Airbnb", "site": "greenhouse", "slug": "airbnb"},
    {"company": "Stripe", "site": "greenhouse", "slug": "stripe"},
]


def active_companies(allowlist: list[str] | None = None) -> list[dict]:
    companies = [company for company in _ATS_COMPANIES if company["company"] not in _DISABLED_ATS_COMPANIES]
    if not allowlist:
        return companies
    allow = {_norm(item) for item in allowlist if str(item).strip()}
    return [company for company in companies if _norm(company["company"]) in allow]


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _cache_query(company: dict, config: ScraperConfig) -> SearchQuery:
    return SearchQuery(term=f"ats:{company['company']}", location="", country=config.default_country)


def _api_url(company: dict) -> str:
    site = company["site"]
    slug = company["slug"]
    if site == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if site == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    if site == "lever":
        return f"https://api.lever.co/v0/postings/{slug}"
    if site == "smartrecruiters":
        return f"https://careers.smartrecruiters.com/{slug}"
    raise ValueError(f"Unsupported ATS site: {site}")


def _stringify_location(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        parts = []
        for key in ("name", "location", "city", "country"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return ", ".join(dict.fromkeys(parts)) or None
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return ", ".join(dict.fromkeys(parts)) or None
    return None


def _normalize_greenhouse(company: dict, payload: dict) -> list[RawJob]:
    jobs = []
    for item in payload.get("jobs", []) or []:
        url = str(item.get("absolute_url") or "").strip()
        if not url:
            continue
        content = item.get("content")
        if not isinstance(content, str):
            content = ""
        jobs.append(
            RawJob(
                job_url=url,
                title=item.get("title"),
                company=company["company"],
                description=content,
                location=_stringify_location(item.get("location")),
                site="greenhouse",
                date_posted=_parse_date(item.get("updated_at") or item.get("first_published")),
            )
        )
    return jobs


def _normalize_ashby(company: dict, payload: dict) -> list[RawJob]:
    jobs = []
    for item in payload.get("jobs", []) or []:
        url = str(item.get("jobUrl") or "").strip()
        if not url:
            continue
        description = item.get("descriptionHtml") or item.get("descriptionPlain") or ""
        jobs.append(
            RawJob(
                job_url=url,
                title=item.get("title"),
                company=company["company"],
                description=description,
                location=_stringify_location(item.get("location")) or _stringify_location(item.get("locations")),
                site="ashby",
                date_posted=_parse_date(item.get("publishedDate") or item.get("createdAt")),
            )
        )
    return jobs


def _normalize_lever(company: dict, payload) -> list[RawJob]:
    if not isinstance(payload, list):
        return []
    jobs = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = str(item.get("hostedUrl") or "").strip()
        if not url:
            continue
        description = item.get("descriptionPlain") or item.get("description") or ""
        if not isinstance(description, str):
            description = ""
        jobs.append(
            RawJob(
                job_url=url,
                title=item.get("text"),
                company=company["company"],
                description=description,
                location=_stringify_location((item.get("categories") or {}).get("location")),
                site="lever",
                date_posted=_parse_date(item.get("createdAt") or item.get("updatedAt")),
            )
        )
    return jobs


async def _normalize_smartrecruiters(
    client: httpx.AsyncClient, company: dict, html: str
) -> list[RawJob]:
    soup = BeautifulSoup(html, "lxml")
    job_urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.startswith("/"):
            href = f"https://jobs.smartrecruiters.com{href}"
        if "jobs.smartrecruiters.com" not in href:
            continue
        if href not in job_urls:
            job_urls.append(href)

    jobs: list[RawJob] = []
    for url in job_urls:
        try:
            response = await client.get(url, timeout=30)
            response.raise_for_status()
        except Exception:
            continue
        detail = BeautifulSoup(response.text, "lxml")
        title = None
        og_title = detail.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            title = str(og_title["content"]).strip()
        if not title:
            title_tag = detail.find("title")
            title = str(title_tag.get_text(" ", strip=True)) if title_tag else None
        if title and "|" in title:
            title = title.split("|", 1)[0].strip()
        description = None
        desc_tag = detail.find("meta", attrs={"name": "description"})
        if desc_tag and desc_tag.get("content"):
            description = str(desc_tag["content"]).strip()
        if not description:
            description = detail.get_text(" ", strip=True)
        if not title:
            continue
        jobs.append(
            RawJob(
                job_url=url,
                title=title,
                company=company["company"],
                description=description or "",
                location=None,
                site="smartrecruiters",
                date_posted=None,
            )
        )
    return jobs


def _query_tokens(term: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9\+#/]+", str(term or "").lower())
    filtered = [token for token in tokens if token not in _QUERY_STOPWORDS]
    return filtered or tokens


def _matches_query(job: RawJob, query: SearchQuery) -> bool:
    text = f"{job.title or ''} {job.description or ''}".lower()
    raw_term = str(query.term or "").lower().strip()
    if raw_term and raw_term in text:
        title_text = (job.title or "").lower()
        return not query.location or query.location.lower() in (job.location or "").lower() or "remote" in title_text or "remote" in (job.location or "").lower()

    tokens = _query_tokens(query.term)
    if not tokens:
        return False
    overlap = sum(1 for token in tokens if token in text)
    needed = min(2, len(tokens))
    if overlap < needed:
        return False

    if not query.location:
        return True

    loc = (job.location or "").lower()
    query_loc = query.location.lower()
    return query_loc in loc or ("remote" in loc and query_loc in {"remote", ""})


async def _fetch_board(client: httpx.AsyncClient, company: dict) -> list[RawJob]:
    response = await client.get(_api_url(company), timeout=30)
    response.raise_for_status()
    if company["site"] == "smartrecruiters":
        return await _normalize_smartrecruiters(client, company, response.text)
    payload = response.json()
    if company["site"] == "greenhouse":
        return _normalize_greenhouse(company, payload)
    if company["site"] == "ashby":
        return _normalize_ashby(company, payload)
    return _normalize_lever(company, payload)


async def probe_company(client: httpx.AsyncClient, company: dict) -> dict[str, str | int]:
    try:
        response = await client.get(_api_url(company), timeout=30)
        return {
            "company": company["company"],
            "site": company["site"],
            "slug": company["slug"],
            "status": response.status_code,
            "url": str(response.url),
        }
    except Exception as exc:
        return {
            "company": company["company"],
            "site": company["site"],
            "slug": company["slug"],
            "status": type(exc).__name__,
            "url": _api_url(company),
        }


async def search(queries: list[SearchQuery], config: ScraperConfig, db: AsyncSession | None = None) -> list[RawJob]:
    if not queries:
        return []

    all_jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient() as client:
        for company in active_companies(config.company_allowlist):
            cache_query = _cache_query(company, config)
            try:
                cached = await load_cached_jobs(
                    db,
                    provider="ats_direct",
                    site=company["site"],
                    query=cache_query,
                    config=config,
                )
                if cached is None:
                    jobs = await _fetch_board(client, company)
                    await store_cached_jobs(
                        db,
                        provider="ats_direct",
                        site=company["site"],
                        query=cache_query,
                        config=config,
                        jobs=jobs,
                    )
                else:
                    jobs = cached
            except Exception:
                logger.exception("ATS direct fetch failed for %s", company["company"])
                jobs = []

            for job in jobs:
                if job.job_url in seen_urls:
                    continue
                if any(_matches_query(job, query) for query in queries):
                    seen_urls.add(job.job_url)
                    all_jobs.append(job)
            await asyncio.sleep(0.1)

    return all_jobs
