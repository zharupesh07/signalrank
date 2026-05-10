from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal
from urllib.parse import parse_qsl, unquote, urlparse

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Application, JobRaw, JobResult

logger = logging.getLogger(__name__)

AvailabilityStatus = Literal["available", "expired", "unknown"]

EXPIRED_REASON = "Job posting is expired or no longer available"

EXPIRED_PATTERNS = (
    re.compile(r"\bjob (?:has )?expired\b", re.IGNORECASE),
    re.compile(r"\bjob posting (?:has )?expired\b", re.IGNORECASE),
    re.compile(r"\bjob (?:is )?no longer available\b", re.IGNORECASE),
    re.compile(r"\bjob posting (?:is )?no longer available\b", re.IGNORECASE),
    re.compile(r"\bposition (?:has been )?filled\b", re.IGNORECASE),
    re.compile(r"\bno longer accepting applications\b", re.IGNORECASE),
    re.compile(r"\bnot accepting applications\b", re.IGNORECASE),
)

BLOCKED_PATTERNS = (
    re.compile(r"\bsecurity check\b", re.IGNORECASE),
    re.compile(r"\bcaptcha\b", re.IGNORECASE),
    re.compile(r"\bcloudflare\b", re.IGNORECASE),
    re.compile(r"INDEED_CLOUDFLARE_STATIC_PAGE", re.IGNORECASE),
)

JOB_BOARD_HOST_SUFFIXES = (
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "google.com",
)

DIRECT_URL_QUERY_KEYS = {
    "adurl",
    "destination",
    "redirect",
    "redirect_url",
    "rurl",
    "rx_url",
    "target",
    "u",
    "url",
}

MAX_AVAILABILITY_CANDIDATE_URLS = 5


@dataclass(frozen=True)
class JobAvailability:
    url: str
    status: AvailabilityStatus
    reason: str | None = None
    status_code: int | None = None
    final_url: str | None = None


@dataclass(frozen=True)
class AvailabilityDecision:
    availability: JobAvailability
    checked_urls: tuple[str, ...]
    confirmation: JobAvailability | None = None


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _is_job_board_url(url: str) -> bool:
    host = _host(url)
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in JOB_BOARD_HOST_SUFFIXES
    )


def is_job_board_url(url: str) -> bool:
    return _is_job_board_url(url)


def _normalize_http_url(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    return None


def _availability_candidate_urls_from_one_url(job_url: str) -> list[str]:
    direct_urls: list[str] = []
    wrapper_urls: list[str] = []
    seen: set[str] = set()
    original = _normalize_http_url(job_url)
    if not original:
        return []

    parsed = urlparse(original)

    def add(url: str, *, direct: bool) -> None:
        normalized = _normalize_http_url(url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        if direct:
            direct_urls.append(normalized)
        else:
            wrapper_urls.append(normalized)

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized = _normalize_http_url(value)
        if not normalized:
            continue
        key_lower = key.lower()
        is_direct_key = key_lower in DIRECT_URL_QUERY_KEYS or key_lower.endswith("_url")
        add(normalized, direct=is_direct_key and not _is_job_board_url(normalized))

    add(original, direct=not _is_job_board_url(original))
    return [*direct_urls, *wrapper_urls][:MAX_AVAILABILITY_CANDIDATE_URLS]


def availability_candidate_urls(
    job_url: str,
    availability_urls: list | None = None,
) -> list[str]:
    direct_urls: list[str] = []
    wrapper_urls: list[str] = []
    seen: set[str] = set()

    for url in [*(availability_urls or []), job_url]:
        if not isinstance(url, str):
            continue
        for candidate in _availability_candidate_urls_from_one_url(url):
            if candidate not in seen:
                seen.add(candidate)
                if _is_job_board_url(candidate):
                    wrapper_urls.append(candidate)
                else:
                    direct_urls.append(candidate)
    return [*direct_urls, *wrapper_urls]


def classify_job_page(
    *,
    url: str,
    status_code: int,
    text: str,
    final_url: str | None = None,
) -> JobAvailability:
    if status_code in {404, 410}:
        return JobAvailability(
            url=url,
            status="expired",
            reason=f"{EXPIRED_REASON} (HTTP {status_code})",
            status_code=status_code,
            final_url=final_url,
        )

    blocked = any(pattern.search(text) for pattern in BLOCKED_PATTERNS)
    if status_code in {401, 403, 429} or blocked:
        return JobAvailability(
            url=url,
            status="unknown",
            reason=f"Availability check blocked or rate-limited (HTTP {status_code})",
            status_code=status_code,
            final_url=final_url,
        )

    for pattern in EXPIRED_PATTERNS:
        if pattern.search(text):
            return JobAvailability(
                url=url,
                status="expired",
                reason=EXPIRED_REASON,
                status_code=status_code,
                final_url=final_url,
            )

    if 200 <= status_code < 400:
        return JobAvailability(
            url=url,
            status="available",
            status_code=status_code,
            final_url=final_url,
        )

    return JobAvailability(
        url=url,
        status="unknown",
        reason=f"Unexpected availability response (HTTP {status_code})",
        status_code=status_code,
        final_url=final_url,
    )


async def check_job_availability(
    url: str,
    *,
    timeout: float = 12.0,
    client: httpx.AsyncClient | None = None,
) -> JobAvailability:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def _get(active_client: httpx.AsyncClient) -> JobAvailability:
        response = await active_client.get(url, headers=headers)
        return classify_job_page(
            url=url,
            status_code=response.status_code,
            text=response.text[:200_000],
            final_url=str(response.url),
        )

    try:
        if client is not None:
            return await _get(client)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
        ) as owned_client:
            return await _get(owned_client)
    except httpx.HTTPError as exc:
        logger.warning("Job availability check failed for %s: %s", url, exc)
        return JobAvailability(url=url, status="unknown", reason=str(exc)[:300])


AvailabilityChecker = Callable[[str], Awaitable[JobAvailability]]


async def reliable_job_availability(
    job_url: str,
    *,
    availability_urls: list | None = None,
    checker: AvailabilityChecker = check_job_availability,
) -> AvailabilityDecision:
    candidates = availability_candidate_urls(
        job_url,
        availability_urls=availability_urls,
    )
    checked_urls: list[str] = []
    first_unknown: JobAvailability | None = None
    last_result: JobAvailability | None = None

    for url in candidates:
        availability = await checker(url)
        checked_urls.append(url)
        last_result = availability

        if availability.status == "available":
            return AvailabilityDecision(
                availability=availability,
                checked_urls=tuple(checked_urls),
            )

        if availability.status == "unknown":
            first_unknown = first_unknown or availability
            continue

        confirmation = await checker(url)
        if confirmation.status == "expired":
            return AvailabilityDecision(
                availability=availability,
                checked_urls=tuple(checked_urls),
                confirmation=confirmation,
            )
        if confirmation.status == "available":
            return AvailabilityDecision(
                availability=confirmation,
                checked_urls=tuple(checked_urls),
                confirmation=confirmation,
            )
        return AvailabilityDecision(
            availability=JobAvailability(
                url=url,
                status="unknown",
                reason="Expired signal was not confirmed on second check",
                status_code=confirmation.status_code,
                final_url=confirmation.final_url,
            ),
            checked_urls=tuple(checked_urls),
            confirmation=confirmation,
        )

    fallback = first_unknown or last_result or JobAvailability(
        url=job_url,
        status="unknown",
        reason="No valid HTTP URL for availability check",
    )
    return AvailabilityDecision(
        availability=fallback,
        checked_urls=tuple(checked_urls),
    )


async def archive_expired_jobs_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    run_id: str | None = None,
    urls: list[str] | None = None,
    limit: int = 50,
    checker: AvailabilityChecker = check_job_availability,
) -> dict:
    stmt = (
        select(JobResult, JobRaw)
        .join(JobRaw, JobRaw.id == JobResult.job_id)
        .where(JobResult.user_id == user_id)
        .where(
            or_(
                JobResult.archived_by_llm.is_(None),
                JobResult.archived_by_llm.is_(False),
            )
        )
        .order_by(JobResult.final_score.desc().nulls_last(), JobRaw.ingested_at.desc())
        .limit(max(1, min(limit, 1000)))
    )
    if run_id:
        stmt = stmt.where(JobResult.run_id == run_id)
    if urls:
        normalized_urls = [url.strip() for url in urls if url.strip()]
        stmt = stmt.where(JobRaw.job_url.in_(normalized_urls))

    rows = (await db.execute(stmt)).all()
    archived = 0
    tracker_archived = 0
    checked: list[dict] = []

    for result, job in rows:
        decision = await reliable_job_availability(
            job.job_url,
            availability_urls=job.availability_urls,
            checker=checker,
        )
        availability = decision.availability
        item = {
            "job_id": job.id,
            "job_result_id": result.id,
            "url": job.job_url,
            "checked_url": availability.url,
            "checked_urls": list(decision.checked_urls),
            "title": job.title,
            "company": job.company,
            "status": availability.status,
            "reason": availability.reason,
            "status_code": availability.status_code,
            "final_url": availability.final_url,
            "confirm_status": (
                decision.confirmation.status if decision.confirmation else None
            ),
            "confirm_reason": (
                decision.confirmation.reason if decision.confirmation else None
            ),
            "confirm_status_code": (
                decision.confirmation.status_code if decision.confirmation else None
            ),
            "confirm_final_url": (
                decision.confirmation.final_url if decision.confirmation else None
            ),
        }
        checked.append(item)
        if availability.status != "expired":
            continue

        result.archived_by_llm = True
        result.archival_reason = (availability.reason or EXPIRED_REASON)[:500]
        archived += 1
        tracker_rows = (
            await db.execute(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.job_id == job.id,
                    Application.status != "archived",
                )
            )
        ).scalars().all()
        for tracker_row in tracker_rows:
            tracker_row.status = "archived"
            tracker_archived += 1

    if archived:
        await db.commit()

    return {
        "checked": len(checked),
        "archived": archived,
        "tracker_archived": tracker_archived,
        "expired": sum(1 for item in checked if item["status"] == "expired"),
        "unknown": sum(1 for item in checked if item["status"] == "unknown"),
        "jobs": checked,
    }
