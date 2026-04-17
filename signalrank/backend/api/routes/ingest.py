"""Job ingest — two-step: extract (no DB) then confirm (DB writes)."""
import ipaddress
import logging
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Application, GenerationQueue, JobRaw, JobResult, Profile, User
from api.rate_limits import enforce_user_rate_limit
from batch.context import load_base_config
from domain.job_profile import build_job_profile
from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["ingest"])

_EXTRACT_SYSTEM = """Extract structured fields from a job posting.

Return a single JSON object only using these keys:
- title: job title
- company: company name
- location: city/country or "Remote"
- job_url: canonical job URL, or empty string
- date_posted: ISO date YYYY-MM-DD if visible on page, else empty string
- description: first 500 characters of job description"""

_EXTRACT_SYSTEM_NO_DATE = """Extract structured fields from a job posting.

Return a single JSON object only using these keys:
- title: job title
- company: company name
- location: city/country or "Remote"
- job_url: canonical job URL, or empty string
- date_posted: empty string
- description: first 500 characters of job description"""

_INGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "company": {"type": "string"},
        "location": {"type": "string"},
        "job_url": {"type": "string"},
        "date_posted": {"type": ["string", "null"]},
        "description": {"type": "string"},
    },
    "required": ["title", "company", "location", "job_url", "date_posted", "description"],
    "additionalProperties": False,
}


def _parse_ingest_response(text: str) -> dict:
    def _field(name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+)", text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    desc_m = re.search(r"^DESCRIPTION:\s*(.+?)(?=\n[A-Z_]+:|$)", text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    description = desc_m.group(1).strip() if desc_m else ""

    return {
        "title": _field("TITLE"),
        "company": _field("COMPANY"),
        "location": _field("LOCATION"),
        "job_url": _field("JOB_URL"),
        "date_posted": _field("DATE_POSTED"),
        "description": description,
    }


def _compute_priority(date_posted: datetime | None, company_tier: str | None) -> str:
    if date_posted is None:
        return "P1"
    hours_old = (datetime.now(timezone.utc) - date_posted).total_seconds() / 3600
    if hours_old < 48:
        return "P1"
    if company_tier in ("SS", "S"):
        return "P1"
    return "P2"


def _validate_url(url: str) -> None:
    """Raise HTTPException if URL is unsafe (SSRF protection)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="URL must use http or https")
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=422, detail="Invalid URL")
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise HTTPException(status_code=422, detail="URL not allowed")
    except socket.gaierror:
        raise HTTPException(status_code=422, detail="Could not resolve host")


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class IngestRequest(BaseModel):
    url: str | None = None
    text: str | None = None


class IngestExtracted(BaseModel):
    title: str
    company: str
    location: str
    job_url: str
    date_posted: str | None = None
    description: str


class IngestConfirmRequest(BaseModel):
    title: str
    company: str
    location: str
    job_url: str
    date_posted: str | None = None
    description: str


@router.post("/ingest", response_model=IngestExtracted)
async def ingest_extract(
    body: IngestRequest,
    current_user: User = Depends(get_current_user),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    if not body.url and not body.text:
        raise HTTPException(status_code=422, detail="Provide url or text")
    await enforce_user_rate_limit(
        current_user.id,
        "job_ingest_extract",
        limit=20,
        window_seconds=60 * 60,
    )

    content = body.text or ""
    is_url = bool(body.url)

    if body.url:
        _validate_url(body.url)
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(body.url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                content = _strip_html(resp.text)[:8000]
        except httpx.HTTPStatusError as e:
            retryable = e.response.status_code >= 500
            raise HTTPException(
                status_code=502,
                detail={"error": "fetch_failed", "retryable": retryable, "message": str(e)},
            )
        except (httpx.TimeoutException, httpx.RequestError) as e:
            raise HTTPException(
                status_code=502,
                detail={"error": "fetch_failed", "retryable": True, "message": str(e)},
            )

    system = _EXTRACT_SYSTEM if is_url else _EXTRACT_SYSTEM_NO_DATE
    user_msg = f"Job posting content:\n\n{content[:8000]}"

    try:
        fields = await llm.llm_json(
            system=system,
            user=user_msg,
            max_tokens=600,
            temperature=0.0,
            json_schema=_INGEST_SCHEMA,
            schema_name="job_ingest_extract",
        )
        if "_error" in fields:
            raise ValueError(fields.get("_details") or "structured ingest extraction failed")
        fields = {
            "title": str(fields.get("title") or "").strip(),
            "company": str(fields.get("company") or "").strip(),
            "location": str(fields.get("location") or "").strip(),
            "job_url": str(fields.get("job_url") or "").strip(),
            "date_posted": str(fields.get("date_posted") or "").strip() or None,
            "description": str(fields.get("description") or "").strip(),
        }
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        raise HTTPException(status_code=502, detail={"error": "parse_failed"})

    return IngestExtracted(**fields)


@router.post("/ingest/confirm")
async def ingest_confirm(
    body: IngestConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_user_rate_limit(
        current_user.id,
        "job_ingest_confirm",
        limit=30,
        window_seconds=60 * 60,
    )
    job_url = (body.job_url or "").strip() or f"manual://{uuid.uuid4()}"

    # Duplicate check — before any DB writes
    if not job_url.startswith("manual://"):
        existing = await db.execute(
            select(Application)
            .join(JobRaw, Application.job_id == JobRaw.id)
            .where(
                Application.user_id == current_user.id,
                JobRaw.job_url == job_url,
            )
        )
        dup = existing.scalar_one_or_none()
        if dup:
            return {"error": "duplicate", "application_id": str(dup.id)}

    # Parse date_posted
    date_posted: datetime | None = None
    if body.date_posted:
        try:
            date_posted = datetime.fromisoformat(body.date_posted).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    existing_job = None
    if not job_url.startswith("manual://"):
        existing_job = (
            await db.execute(select(JobRaw).where(JobRaw.job_url == job_url))
        ).scalar_one_or_none()

    # Look up company tier from job_results (any run, this user)
    tier_result = await db.execute(
        select(JobResult.company_tier)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(
            JobResult.user_id == current_user.id,
            JobRaw.company == body.company,
            JobResult.company_tier.isnot(None),
            JobResult.company_tier.notin_(["default", ""]),
        )
        .order_by(JobResult.final_score.desc())
        .limit(1)
    )
    company_tier = tier_result.scalar_one_or_none()

    priority = _compute_priority(date_posted, company_tier)
    if (
        existing_job
        and isinstance(existing_job.job_profile, dict)
        and existing_job.title == (body.title or None)
        and existing_job.company == (body.company or None)
        and existing_job.description == (body.description or None)
        and existing_job.location == (body.location or None)
        and existing_job.site == "manual"
        and existing_job.date_posted == date_posted
    ):
        job_profile = existing_job.job_profile
        inferred_clusters = list(existing_job.role_clusters or [])
    else:
        from domain.role_clusters import infer_clusters_from_job_text

        inferred_clusters = sorted(
            infer_clusters_from_job_text(body.title or None, body.description or None) - {"general"}
        )
        job_profile = build_job_profile(
            title=body.title,
            company=body.company,
            description=body.description,
            location=body.location,
            site="manual",
            date_posted=date_posted,
            role_clusters=inferred_clusters,
            cfg=load_base_config(),
        )

    # Upsert JobRaw (shared across users) — tag by job content, not by the current user's profile.
    insert_stmt = pg_insert(JobRaw).values(
            job_url=job_url,
            title=body.title or None,
            company=body.company or None,
            description=body.description or None,
            location=body.location or None,
            site="manual",
            date_posted=date_posted,
            role_clusters=inferred_clusters,
            job_profile=job_profile,
        )
    await db.execute(
        insert_stmt
        .on_conflict_do_update(
            index_elements=["job_url"],
            set_={
                "role_clusters": insert_stmt.excluded.role_clusters,
                "job_profile": insert_stmt.excluded.job_profile,
            },
        )
    )
    await db.flush()

    job_res = await db.execute(select(JobRaw).where(JobRaw.job_url == job_url))
    job = job_res.scalar_one()

    # Insert Application (idempotency guard — requires uq_application_user_job constraint)
    app_insert = await db.execute(
        pg_insert(Application)
        .values(
            user_id=current_user.id,
            job_id=job.id,
            company=body.company or None,
            title=body.title or None,
            status="interested",
            priority=priority,
        )
        .on_conflict_do_nothing(constraint="uq_application_user_job")
        .returning(Application.id)
    )
    app_id_row = app_insert.fetchone()

    if not app_id_row:
        existing_app = await db.execute(
            select(Application).where(
                Application.user_id == current_user.id,
                Application.job_id == job.id,
            )
        )
        app_id = str(existing_app.scalar_one().id)
    else:
        app_id = str(app_id_row[0])

    # Enqueue generation
    await db.execute(
        pg_insert(GenerationQueue)
        .values(user_id=current_user.id, job_id=job.id)
        .on_conflict_do_nothing(constraint="uq_generation_queue_user_job")
    )
    await db.commit()

    logger.info("Ingested job '%s' @ '%s' for user=%s priority=%s", body.title, body.company, current_user.id, priority)
    return {"application_id": app_id, "priority": priority}
