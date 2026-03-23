import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, get_db
from api.deps import get_current_user
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


async def _run_refresh(task_id: str, user_id: str, companies: list[str], session_factory):
    """Background coroutine: refreshes recruiters for all companies."""
    async with session_factory() as db:
        result = await db.execute(select(RecruiterRefreshTask).where(RecruiterRefreshTask.id == task_id))
        task = result.scalar_one()
        total = len(companies)
        new_found = 0

        for i, company in enumerate(companies):
            task.progress_json = {"done": i, "total": total, "current": company}
            await db.commit()
            try:
                found = await find_recruiters(company=company, max_results=10, db=db)
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
            except Exception as exc:
                logger.warning("Refresh failed for %s: %s", company, exc)
            await asyncio.sleep(3)

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
        bg = asyncio.create_task(
            _run_refresh(task_id, current_user.id, companies, AsyncSessionLocal)
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


@router.post("/find", status_code=200)
async def find_and_save_recruiters(
    body: RecruiterFindRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.company.strip():
        raise HTTPException(status_code=422, detail="company is required")
    if body.max_results < 1 or body.max_results > 25:
        raise HTTPException(status_code=422, detail="max_results must be 1-25")

    found = await find_recruiters(
        company=body.company.strip(),
        max_results=body.max_results,
        db=db,
    )

    inserted = 0
    skipped = 0
    saved = []
    for rec in found:
        stmt = (
            pg_insert(Recruiter)
            .values(
                company=body.company.strip(),
                name=rec["name"],
                email=None,
                linkedin_url=rec["linkedin_url"],
                domain=None,
            )
            .on_conflict_do_nothing(constraint="uq_recruiter_company_linkedin")
        )
        result = await db.execute(stmt)
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
        saved.append({
            "name": rec["name"],
            "linkedin_url": rec["linkedin_url"],
            "confidence": rec["confidence"],
        })

    await db.commit()
    return {"found": len(found), "inserted": inserted, "skipped": skipped, "recruiters": saved}


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
