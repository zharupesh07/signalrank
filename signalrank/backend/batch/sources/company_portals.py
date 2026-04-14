from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus, urljoin

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

_COMPANIES = [
    {"company": "Adobe", "slug": "adobe", "kind": "adobe"},
    {"company": "Salesforce", "slug": "salesforce", "kind": "salesforce"},
    {"company": "Optum", "slug": "optum", "kind": "optum"},
    {"company": "SAP", "slug": "sap", "kind": "sap"},
    {"company": "Siemens Energy", "slug": "siemens_energy", "kind": "siemens_energy"},
]


def active_companies(allowlist: list[str] | None = None) -> list[dict[str, str]]:
    if not allowlist:
        return list(_COMPANIES)
    allow = {_norm(item) for item in allowlist if str(item).strip()}
    return [company for company in _COMPANIES if _norm(company["company"]) in allow]


def _parse_date(value: Any) -> datetime | None:
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


def _portal_search_terms(query: SearchQuery) -> list[str]:
    raw = str(query.term or "").strip()
    lowered = raw.lower()
    terms = [raw]
    if any(token in lowered for token in ("agent", "agentic", "genai", "llm", "mlops", "ml platform")):
        for fallback in ("AI", "Machine Learning", "Generative AI"):
            if fallback.lower() != lowered:
                terms.append(fallback)
    return list(dict.fromkeys(term for term in terms if term))


def _matches_query(job: RawJob, query: SearchQuery) -> bool:
    text = f"{job.title or ''} {job.description or ''}".lower()
    raw_term = str(query.term or "").lower().strip()
    if raw_term and raw_term in text:
        return _matches_location(query, job.location)

    tokens = _query_tokens(query.term)
    if not tokens:
        return False
    overlap = sum(1 for token in tokens if token in text)
    needed = min(2, len(tokens))
    if overlap < needed:
        return False
    return _matches_location(query, job.location)


def _matches_search_term(
    *, title: str | None, description: str | None, location: str | None, search_term: str, query: SearchQuery
) -> bool:
    text = f"{title or ''} {description or ''}".lower()
    raw_term = str(search_term or "").lower().strip()
    if raw_term and raw_term in text:
        return _matches_location(query, location)
    tokens = _query_tokens(search_term)
    if not tokens:
        return False
    overlap = sum(1 for token in tokens if token in text)
    needed = 1 if len(tokens) == 1 else min(2, len(tokens))
    if overlap < needed:
        return False
    return _matches_location(query, location)


def _matches_location(query: SearchQuery, location: str | None) -> bool:
    if not query.location:
        return True
    loc = str(location or "").lower()
    query_loc = query.location.lower()
    if query_loc in {"bangalore", "bengaluru"} and any(city in loc for city in ("bangalore", "bengaluru")):
        return True
    if query_loc in {"delhi", "new delhi"} and any(city in loc for city in ("delhi", "new delhi")):
        return True
    if query_loc in {"gurgaon", "gurugram"} and any(city in loc for city in ("gurgaon", "gurugram")):
        return True
    return query_loc in loc or ("remote" in loc and query_loc in {"remote", ""})


def _json_ld_object(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return {}


def _job_location_from_jsonld(payload: dict[str, Any]) -> str | None:
    job_location = payload.get("jobLocation")
    items = job_location if isinstance(job_location, list) else [job_location]
    parts: list[str] = []
    for item in items:
        address = item.get("address") if isinstance(item, dict) else None
        if not isinstance(address, dict):
            continue
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if not parts:
        return None
    return ", ".join(dict.fromkeys(parts))


def _extract_phapp_ddo(html: str) -> dict[str, Any]:
    match = re.search(r"phApp\.ddo\s*=\s*(\{.*?\})\s*;\s*phApp\.experimentData", html, re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _fetch_adobe_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for search_term in _portal_search_terms(query):
        response = await client.get(
            "https://careers.adobe.com/us/en/search-results",
            params={"keywords": search_term},
            timeout=30,
        )
        response.raise_for_status()
        ddo = _extract_phapp_ddo(response.text)
        payload = ((ddo.get("eagerLoadRefineSearch") or {}).get("data") or {})
        for item in payload.get("jobs") or []:
            if not isinstance(item, dict):
                continue
            job_seq_no = str(item.get("jobSeqNo") or "").strip()
            title = str(item.get("title") or "").strip()
            if not job_seq_no or not title:
                continue
            job_url = f"https://careers.adobe.com/us/en/job/{job_seq_no}/{quote_plus(title.replace('/', '-'))}"
            if job_url in seen:
                continue
            location = str(item.get("location") or item.get("cityStateCountry") or "").strip() or None
            preview_text = " ".join(
                part for part in [
                    title,
                    str(item.get("descriptionTeaser") or "").strip(),
                    str(item.get("ml_job_parser") or "").strip(),
                ] if part
            )
            if not _matches_search_term(
                title=title,
                description=preview_text,
                location=location,
                search_term=search_term,
                query=query,
            ):
                continue
            seen.add(job_url)
            jobs.append(
                RawJob(
                    job_url=job_url,
                    title=title,
                    company=company["company"],
                    description=str(item.get("descriptionTeaser") or "").strip(),
                    location=location,
                    site="company_portal",
                    date_posted=_parse_date(item.get("postedDate") or item.get("dateCreated")),
                )
            )
    return jobs


async def _fetch_salesforce_detail(
    client: httpx.AsyncClient, company: dict[str, str], url: str, title: str, location: str | None
) -> RawJob | None:
    response = await client.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    payload = _json_ld_object(soup)
    description = str(payload.get("description") or "")
    return RawJob(
        job_url=url,
        title=str(payload.get("title") or title).strip() or title,
        company=company["company"],
        description=description,
        location=_job_location_from_jsonld(payload) or location,
        site="company_portal",
        date_posted=_parse_date(payload.get("datePosted")),
    )


async def _fetch_salesforce_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for search_term in _portal_search_terms(query):
        params = {"search": search_term}
        if query.location:
            params["location"] = query.location
        response = await client.get(
            "https://careers.salesforce.com/en/jobs/",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for card in soup.select("h3.card-title"):
            anchor = card.find("a", href=True)
            if not anchor:
                continue
            url = urljoin("https://careers.salesforce.com", str(anchor["href"]).strip())
            if url in seen:
                continue
            title = anchor.get_text(" ", strip=True)
            location_list = card.find_next("ul", class_="locations")
            location = location_list.get_text(" ", strip=True) if location_list else None
            if not _matches_search_term(
                title=title,
                description="",
                location=location,
                search_term=search_term,
                query=query,
            ):
                continue
            seen.add(url)
            try:
                job = await _fetch_salesforce_detail(client, company, url, title, location)
            except Exception:
                logger.exception("Salesforce detail fetch failed for %s", url)
                continue
            if job is not None:
                jobs.append(job)
    return jobs


async def _fetch_optum_detail(
    client: httpx.AsyncClient, company: dict[str, str], url: str, title: str
) -> RawJob | None:
    response = await client.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    payload = _json_ld_object(soup)
    description = str(payload.get("description") or "")
    visible_location = None
    location_tag = soup.find(class_="job-location") or soup.find("span", class_="job-location")
    if location_tag:
        visible_location = location_tag.get_text(" ", strip=True)
    return RawJob(
        job_url=url,
        title=str(payload.get("title") or title).strip() or title,
        company=company["company"],
        description=description,
        location=_job_location_from_jsonld(payload) or visible_location,
        site="company_portal",
        date_posted=_parse_date(payload.get("datePosted")),
    )


async def _fetch_optum_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for search_term in _portal_search_terms(query):
        params = {
            "k": search_term,
            "l": query.location or query.country,
            "orgIds": "34088",
            "ascf": '[{"key":"custom_fields.UHGAJDType","value":"Optum"}]',
        }
        response = await client.get(
            "https://careers.unitedhealthgroup.com/search-jobs",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for anchor in soup.select('a[href*="/job/"]'):
            href = str(anchor.get("href") or "").strip()
            if "/job/" not in href or "/34088/" not in href:
                continue
            url = urljoin("https://careers.unitedhealthgroup.com", href)
            if url in seen:
                continue
            title = anchor.get_text(" ", strip=True).split("|", 1)[0].strip()
            if not title:
                continue
            preview_text = anchor.get_text(" ", strip=True)
            if not _matches_search_term(
                title=title,
                description=preview_text,
                location=preview_text,
                search_term=search_term,
                query=query,
            ):
                continue
            seen.add(url)
            try:
                job = await _fetch_optum_detail(client, company, url, title)
            except Exception:
                logger.exception("Optum detail fetch failed for %s", url)
                continue
            if job is not None:
                jobs.append(job)
    return jobs


async def _fetch_sap_detail(
    client: httpx.AsyncClient, company: dict[str, str], url: str, title: str
) -> RawJob | None:
    response = await client.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    description_tag = soup.select_one(".jobdescription")
    description = description_tag.get_text(" ", strip=True) if description_tag else ""
    location_tag = soup.select_one(".jobLocation .jobGeoLocation")
    location = location_tag.get_text(" ", strip=True) if location_tag else None
    date_tag = soup.find("span", class_="jobdate")
    return RawJob(
        job_url=url,
        title=title,
        company=company["company"],
        description=description,
        location=location,
        site="company_portal",
        date_posted=_parse_date(date_tag.get_text(" ", strip=True) if date_tag else None),
    )


async def _fetch_sap_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for search_term in _portal_search_terms(query):
        response = await client.get(
            "https://jobs.sap.com/search/",
            params={"q": search_term, "locationsearch": query.location or query.country},
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for anchor in soup.select('a[href*="/job/"]'):
            href = str(anchor.get("href") or "").strip()
            if "/job/" not in href:
                continue
            url = urljoin("https://jobs.sap.com", href)
            if url in seen:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            if not _matches_search_term(
                title=title,
                description=title,
                location=str(query.location or query.country),
                search_term=search_term,
                query=query,
            ):
                continue
            seen.add(url)
            try:
                job = await _fetch_sap_detail(client, company, url, title)
            except Exception:
                logger.exception("SAP detail fetch failed for %s", url)
                continue
            jobs.append(job)
    return jobs


async def _fetch_siemens_energy_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for search_term in _portal_search_terms(query):
        response = await client.post(
            "https://jobs.siemens-energy.com/en_US/jobs/Jobs",
            data={"29494": search_term, "29495-submit": "search", "action": "search"},
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        for anchor in soup.select('a[href*="/FolderDetail/"]'):
            href = str(anchor.get("href") or "").strip()
            match = re.search(r"/FolderDetail/[^/]+/(\d+)", href)
            if not match:
                continue
            folder_id = match.group(1)
            detail_url = urljoin("https://jobs.siemens-energy.com", href)
            if detail_url in seen:
                continue
            title = anchor.get_text(" ", strip=True)
            if not _matches_search_term(
                title=title,
                description=title,
                location=str(query.location or query.country),
                search_term=search_term,
                query=query,
            ):
                continue
            seen.add(detail_url)
            try:
                detail = await client.post(
                    "https://jobs.siemens-energy.com/en_US/jobs/JobInfo",
                    data={"folderId": folder_id},
                    timeout=30,
                )
                detail.raise_for_status()
            except Exception:
                logger.exception("Siemens Energy detail fetch failed for %s", detail_url)
                continue
            detail_soup = BeautifulSoup(detail.text, "lxml")
            description = detail_soup.get_text(" ", strip=True)
            jobs.append(
                RawJob(
                    job_url=detail_url,
                    title=title,
                    company=company["company"],
                    description=description,
                    location=description,
                    site="company_portal",
                    date_posted=None,
                )
            )
    return jobs


async def _fetch_company_jobs(
    client: httpx.AsyncClient, company: dict[str, str], query: SearchQuery
) -> list[RawJob]:
    kind = company["kind"]
    if kind == "salesforce":
        return await _fetch_salesforce_jobs(client, company, query)
    if kind == "adobe":
        return await _fetch_adobe_jobs(client, company, query)
    if kind == "optum":
        return await _fetch_optum_jobs(client, company, query)
    if kind == "sap":
        return await _fetch_sap_jobs(client, company, query)
    if kind == "siemens_energy":
        return await _fetch_siemens_energy_jobs(client, company, query)
    raise ValueError(f"Unsupported company portal kind: {kind}")


async def search(
    queries: list[SearchQuery], config: ScraperConfig, db: AsyncSession | None = None
) -> list[RawJob]:
    if not queries:
        return []

    all_jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
    ) as client:
        for company in active_companies(config.company_allowlist):
            for query in queries:
                try:
                    cached = await load_cached_jobs(
                        db,
                        provider="company_portals",
                        site=company["slug"],
                        query=query,
                        config=config,
                    )
                    if cached is None:
                        jobs = await _fetch_company_jobs(client, company, query)
                        await store_cached_jobs(
                            db,
                            provider="company_portals",
                            site=company["slug"],
                            query=query,
                            config=config,
                            jobs=jobs,
                        )
                    else:
                        jobs = cached
                except Exception:
                    logger.exception("Company portal fetch failed for %s", company["company"])
                    jobs = []

                for job in jobs:
                    if job.job_url in seen_urls:
                        continue
                    if _matches_query(job, query):
                        seen_urls.add(job.job_url)
                        all_jobs.append(job)
                await asyncio.sleep(0.1)

    return all_jobs
