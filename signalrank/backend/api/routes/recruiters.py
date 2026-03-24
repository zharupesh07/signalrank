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
from api.deps_llm import get_llm_client
from api.models import Application, Recruiter, RecruiterRefreshTask, User
from batch.recruiter_finder import find_recruiters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recruiters", tags=["recruiters"])

_background_tasks: set[asyncio.Task] = set()


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


async def _run_refresh(task_id: str, user_id: str, companies: list[str], session_factory, llm):
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
                    found = await find_recruiters(company=company, max_results=10, db=db, llm=llm)
                    for rec in found:
                        stmt = (
                            pg_insert(Recruiter)
                            .values(company=company, name=rec["name"], linkedin_url=rec["linkedin_url"])
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

            # Rate limiting: space out companies to avoid hammering DDG
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
        bg = asyncio.create_task(
            _run_refresh(task_id, current_user.id, companies, AsyncSessionLocal, llm)
        )
        _background_tasks.add(bg)
        bg.add_done_callback(_background_tasks.discard)

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


async def _run_find_one(company: str, max_results: int, session_factory, llm):
    """Background: find recruiters for a single company and persist them."""
    async with session_factory() as db:
        MAX_RETRIES = 3
        for attempt in range(MAX_RETRIES):
            try:
                found = await find_recruiters(company=company, max_results=max_results, db=db, llm=llm)
                for rec in found:
                    stmt = (
                        pg_insert(Recruiter)
                        .values(company=company, name=rec["name"], email=None,
                                linkedin_url=rec["linkedin_url"], domain=None)
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
    if not body.company.strip():
        raise HTTPException(status_code=422, detail="company is required")
    if body.max_results < 1 or body.max_results > 25:
        raise HTTPException(status_code=422, detail="max_results must be 1-25")

    llm = get_llm_client()
    bg = asyncio.create_task(_run_find_one(body.company.strip(), body.max_results, AsyncSessionLocal, llm))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)

    return {"status": "queued", "company": body.company.strip()}


@router.get("")
async def list_recruiters(
    company: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Recruiter)
    if company:
        q = q.where(Recruiter.company == company)
    result = await db.execute(q.order_by(Recruiter.company, Recruiter.name))
    recs = result.scalars().all()
    return [
        {
            "id": r.id,
            "company": r.company,
            "name": r.name,
            "email": r.email,
            "linkedin_url": r.linkedin_url,
            "domain": r.domain,
        }
        for r in recs
    ]
