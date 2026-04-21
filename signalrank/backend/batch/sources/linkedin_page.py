from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from batch.query_builder import SearchQuery
from batch.scrape_cache import load_cached_jobs, store_cached_jobs
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)

LINKEDIN_SEARCH_BASE = "https://www.linkedin.com/jobs/search-results/"
LINKEDIN_JOB_URL_PREFIX = "https://www.linkedin.com/jobs/view/"
LINKEDIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _build_search_url(query: SearchQuery) -> str:
    params = {"keywords": query.term}
    location = query.location.strip() or query.country.strip()
    if location:
        params["location"] = location
    return f"{LINKEDIN_SEARCH_BASE}?{urlencode(params)}"


def _build_headers(config: ScraperConfig) -> dict[str, str]:
    headers = {
        "User-Agent": LINKEDIN_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.linkedin.com/jobs/",
    }
    cookie_header = (config.linkedin_cookie_header or "").strip()
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _normalize_job_url(href: str) -> str:
    absolute = urljoin("https://www.linkedin.com", href)
    parsed = urlparse(absolute)
    return parsed._replace(query="", fragment="").geturl()


def _first_text(card, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = card.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return None


def _parse_date(card) -> datetime | None:
    time_node = card.select_one("time[datetime]")
    if time_node:
        raw = (time_node.get("datetime") or "").strip()
        if raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
    return None


def _extract_job_cards(html: str) -> list[RawJob]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    for anchor in soup.select(f'a[href*="/jobs/view/"]'):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        url = _normalize_job_url(href)
        if not url.startswith(LINKEDIN_JOB_URL_PREFIX) or url in seen_urls:
            continue

        card = (
            anchor.find_parent("li")
            or anchor.find_parent("article")
            or anchor.find_parent("div")
            or anchor
        )
        title = _first_text(card, ("h3", "h4", ".base-search-card__title", ".job-card-list__title"))
        if not title:
            title = anchor.get_text(" ", strip=True) or None

        company = _first_text(
            card,
            (
                ".base-search-card__subtitle",
                ".job-card-container__company-name",
                ".job-card-container__primary-description",
                "h4",
            ),
        )
        location = _first_text(
            card,
            (
                ".job-search-card__location",
                ".job-card-container__metadata-item",
                ".base-search-card__metadata",
                "span[class*='location']",
            ),
        )
        description = _first_text(
            card,
            (
                ".job-card-container__description",
                ".base-search-card__description",
                ".job-search-card__snippet",
            ),
        )

        seen_urls.add(url)
        jobs.append(
            RawJob(
                job_url=url,
                title=title,
                company=company,
                description=description,
                location=location,
                site="linkedin_page",
                date_posted=_parse_date(card),
            )
        )

    return jobs


async def _fetch_html(url: str, config: ScraperConfig) -> tuple[str, str]:
    async with httpx.AsyncClient(
        headers=_build_headers(config),
        follow_redirects=True,
        timeout=30,
    ) as client:
        resp = await client.get(url)
        final_url = str(resp.url)
        html = resp.text
    return html, final_url


async def scrape_url(url: str, config: ScraperConfig) -> list[RawJob]:
    html, final_url = await _fetch_html(url, config)
    if "/uas/login" in final_url or "LinkedIn Login" in html:
        logger.warning("LinkedIn search page redirected to login for %s", url)
        return []
    jobs = _extract_job_cards(html)
    logger.info("LinkedIn page scrape: %d jobs from %s", len(jobs), url)
    return jobs


async def search(
    queries: list[SearchQuery],
    config: ScraperConfig,
    db: AsyncSession | None = None,
) -> list[RawJob]:
    all_jobs: list[RawJob] = []
    for query in queries:
        cached = await load_cached_jobs(
            db,
            provider="linkedin_page",
            site="linkedin",
            query=query,
            config=config,
        )
        if cached is not None:
            all_jobs.extend(cached)
            continue

        url = _build_search_url(query)
        try:
            result = await asyncio.wait_for(scrape_url(url, config), timeout=120)
            await store_cached_jobs(
                db,
                provider="linkedin_page",
                site="linkedin",
                query=query,
                config=config,
                jobs=result,
            )
            all_jobs.extend(result)
        except asyncio.TimeoutError:
            logger.warning("LinkedIn page scrape timed out for %s / %s", query.term, query.location)
        except Exception:
            logger.exception("LinkedIn page scrape failed for %s / %s", query.term, query.location)
        await asyncio.sleep(config.jobspy_delay)
    return all_jobs
