import asyncio
import logging
import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, get_db
from api.deps import get_current_user
from api.deps_hunter import get_hunter_client
from api.deps_llm import get_llm_client
from api.models import Application, Recruiter, RecruiterRefreshTask, User
from api.rate_limits import enforce_user_rate_limit
from batch.recruiter_finder import find_recruiters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recruiters", tags=["recruiters"])

_background_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception():
        logger.error("Background task failed: %s", task.exception(), exc_info=task.exception())


async def _get_or_create_refresh_task(db: AsyncSession, user_id: str) -> tuple[str, bool]:
    """Returns (task_id, is_new). If a task is already in_progress, returns it."""
    result = await db.execute(
        select(RecruiterRefreshTask).where(
            RecruiterRefreshTask.user_id == user_id,
            RecruiterRefreshTask.status == "in_progress",
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing.id, False

    task = RecruiterRefreshTask(user_id=user_id, status="in_progress", progress_json={"done": 0, "total": 0})
    db.add(task)
    await db.flush()
    return task.id, True


async def _run_refresh(task_id: str, user_id: str, companies: list[str], session_factory, llm, hunter=None):
    """Background coroutine: refreshes recruiters for all companies with retry + backoff."""
    MAX_RETRIES = 3
    async with session_factory() as db:
        result = await db.execute(select(RecruiterRefreshTask).where(RecruiterRefreshTask.id == task_id))
        task = result.scalar_one()
        total = len(companies)
        new_found = 0

        for i, company in enumerate(companies):
            task.progress_json = {"done": i, "total": total, "current": company}
            await db.commit()

            for attempt in range(MAX_RETRIES):
                try:
                    found = await find_recruiters(company=company, max_results=10, db=db, llm=llm, hunter=hunter)
                    for rec in found:
                        stmt = (
                            pg_insert(Recruiter)
                            .values(
                                company=company,
                                name=rec.get("name"),
                                title=rec.get("title"),
                                linkedin_url=rec["linkedin_url"],
                                domain=rec.get("domain"),
                                email=rec.get("email"),
                                confidence=rec.get("confidence"),
                                email_source=rec.get("email_source"),
                                email_verified=rec.get("email_verified"),
                            )
                            .on_conflict_do_nothing()
                        )
                        r = await db.execute(stmt)
                        if r.rowcount:
                            new_found += 1
                    await db.commit()
                    break  # success
                except Exception as exc:
                    backoff = min(2 ** (attempt + 2), 60) + random.uniform(0, 5)
                    logger.warning("Refresh attempt %d/%d failed for %s: %s — retrying in %.1fs",
                                   attempt + 1, MAX_RETRIES, company, exc, backoff)
                    await asyncio.sleep(backoff)
            else:
                logger.error("Refresh exhausted retries for %s", company)

            await asyncio.sleep(5 + random.uniform(0, 3))

        task.status = "done"
        task.finished_at = datetime.now(timezone.utc)
        task.progress_json = {"done": total, "total": total, "new_found": new_found}
        await db.commit()


class RecruiterFindRequest(BaseModel):
    company: str
    max_results: int = 10


@router.post("/refresh-all", status_code=202)
async def refresh_all_recruiters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_user_rate_limit(
        current_user.id,
        "recruiter_refresh_all",
        limit=2,
        window_seconds=60 * 60,
    )
    result = await db.execute(
        select(Application.company)
        .where(Application.user_id == current_user.id, Application.company.isnot(None))
        .distinct()
    )
    companies = [r[0] for r in result.all()]
    if not companies:
        return {"task_id": None, "message": "No tracked companies"}

    task_id, is_new = await _get_or_create_refresh_task(db, current_user.id)
    await db.commit()

    if is_new:
        llm = get_llm_client()
        hunter = get_hunter_client()
        bg = asyncio.create_task(
            _run_refresh(task_id, current_user.id, companies, AsyncSessionLocal, llm, hunter)
        )
        _background_tasks.add(bg)
        bg.add_done_callback(_on_task_done)

    return {"task_id": task_id, "is_new": is_new, "companies": len(companies)}


@router.get("/refresh-status")
async def refresh_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RecruiterRefreshTask)
        .where(RecruiterRefreshTask.user_id == current_user.id)
        .order_by(RecruiterRefreshTask.started_at.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"status": "none"}
    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress_json,
        "started_at": str(task.started_at),
    }


async def _run_find_one(company: str, max_results: int, session_factory, llm, hunter=None):
    """Background: find recruiters for a single company and persist them."""
    async with session_factory() as db:
        MAX_RETRIES = 3
        for attempt in range(MAX_RETRIES):
            try:
                found = await find_recruiters(company=company, max_results=max_results, db=db, llm=llm, hunter=hunter)
                for rec in found:
                    stmt = (
                        pg_insert(Recruiter)
                        .values(
                            company=company,
                            name=rec.get("name"),
                            title=rec.get("title"),
                            linkedin_url=rec["linkedin_url"],
                            domain=rec.get("domain"),
                            email=rec.get("email"),
                            confidence=rec.get("confidence"),
                            email_source=rec.get("email_source"),
                            email_verified=rec.get("email_verified"),
                        )
                        .on_conflict_do_nothing(constraint="uq_recruiter_company_linkedin")
                    )
                    await db.execute(stmt)
                await db.commit()
                logger.info("find_one: saved %d recruiters for %s", len(found), company)
                return
            except Exception as exc:
                backoff = min(2 ** (attempt + 2), 60) + random.uniform(0, 5)
                logger.warning("find_one attempt %d/%d failed for %s: %s — retrying in %.1fs",
                               attempt + 1, MAX_RETRIES, company, exc, backoff)
                await asyncio.sleep(backoff)
        logger.error("find_one exhausted retries for %s", company)


@router.post("/find", status_code=202)
async def find_and_save_recruiters(
    body: RecruiterFindRequest,
    current_user: User = Depends(get_current_user),
):
    await enforce_user_rate_limit(
        current_user.id,
        "recruiter_find",
        limit=6,
        window_seconds=60 * 60,
    )
    if not body.company.strip():
        raise HTTPException(status_code=422, detail="company is required")
    if body.max_results < 1 or body.max_results > 25:
        raise HTTPException(status_code=422, detail="max_results must be 1-25")

    llm = get_llm_client()
    hunter = get_hunter_client()
    bg = asyncio.create_task(_run_find_one(body.company.strip(), body.max_results, AsyncSessionLocal, llm, hunter))
    _background_tasks.add(bg)
    bg.add_done_callback(_on_task_done)

    return {"status": "queued", "company": body.company.strip()}


async def _run_enrich_emails(task_id: str, user_id: str, session_factory, hunter):
    """Background: enrich recruiters that have name but no email via Hunter."""
    from batch.recruiter_finder import _guess_domain

    async with session_factory() as db:
        result = await db.execute(select(RecruiterRefreshTask).where(RecruiterRefreshTask.id == task_id))
        task = result.scalar_one()

        rec_result = await db.execute(
            select(Recruiter).where(
                Recruiter.email.is_(None),
                Recruiter.name.isnot(None),
            )
        )
        recruiters = rec_result.scalars().all()
        total = len(recruiters)
        enriched = 0

        domain_cache: dict[str, str | None] = {}

        for i, rec in enumerate(recruiters):
            task.progress_json = {"done": i, "total": total, "current": rec.company}
            await db.commit()

            company = rec.company or ""
            if company not in domain_cache:
                domain_cache[company] = rec.domain or await _guess_domain(company)
            domain = domain_cache[company]

            if not domain or not rec.name:
                continue

            try:
                email_result = await hunter.find_email(domain, rec.name)
                if email_result:
                    rec.email = email_result.email
                    rec.domain = domain
                    rec.email_source = "hunter"
                    rec.email_verified = email_result.confidence >= 80
                    enriched += 1
                    await db.commit()
            except Exception as exc:
                logger.warning("Hunter enrich failed for %s: %s", rec.name, exc)

            await asyncio.sleep(1)

        task.status = "done"
        task.finished_at = datetime.now(timezone.utc)
        task.progress_json = {"done": total, "total": total, "enriched": enriched}
        await db.commit()


@router.post("/enrich-emails", status_code=202)
async def enrich_emails(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce_user_rate_limit(
        current_user.id,
        "recruiter_enrich_emails",
        limit=2,
        window_seconds=60 * 60,
    )
    hunter = get_hunter_client()
    if hunter is None:
        raise HTTPException(status_code=400, detail="HUNTER_API_KEY not configured")

    task_id, is_new = await _get_or_create_refresh_task(db, current_user.id)
    await db.commit()

    if is_new:
        bg = asyncio.create_task(
            _run_enrich_emails(task_id, current_user.id, AsyncSessionLocal, hunter)
        )
        _background_tasks.add(bg)
        bg.add_done_callback(_on_task_done)

    return {"task_id": task_id, "is_new": is_new}


@router.get("")
async def list_recruiters(
    company: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_company_subq = (
        select(Application.company)
        .where(Application.user_id == current_user.id, Application.company.isnot(None))
        .distinct()
        .scalar_subquery()
    )
    q = select(Recruiter).where(Recruiter.company.in_(user_company_subq))
    if company:
        q = q.where(Recruiter.company == company)
    result = await db.execute(q.order_by(Recruiter.company, Recruiter.name))
    recs = result.scalars().all()
    return [
        {
            "id": r.id,
            "company": r.company,
            "name": r.name,
            "title": r.title,
            "email": r.email,
            "linkedin_url": r.linkedin_url,
            "domain": r.domain,
            "confidence": r.confidence,
            "email_source": r.email_source,
            "email_verified": r.email_verified,
        }
        for r in recs
    ]
