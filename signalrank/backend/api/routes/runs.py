from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from api.config import api_runtime_flags
from api.database import get_db
from api.deps import get_current_user
from api.models import Profile, Run, User
from batch.worker import RunRequest, get_queue

router = APIRouter(prefix="/api/runs", tags=["runs"])
logger = logging.getLogger(__name__)


def _display_status(db_status: str) -> str:
    return "done" if db_status == "success" else db_status


def _jobs_snapshot(progress: dict | None) -> dict | None:
    if not isinstance(progress, dict):
        return None
    cache = progress.get("jobs_cache")
    if not isinstance(cache, dict):
        return None
    default = cache.get("default")
    return default if isinstance(default, dict) else None


class RunResponse(BaseModel):
    run_id: str
    status: str
    job_count: int | None = None
    scrape_count: int | None = None
    progress: dict | None = None
    jobs_snapshot: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class TriggerRunRequest(BaseModel):
    mode: Literal["quick", "full"] = "quick"
    disable_scraping: bool = False
    executor_type: Literal["local", "cloud"] | None = None


async def _create_run(
    *,
    requested_mode: str,
    disable_scraping: bool,
    executor_type: str | None,
    current_user: User,
    db: AsyncSession,
) -> dict[str, str]:
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.onboarding_complete:
        raise HTTPException(status_code=400, detail="Please complete onboarding before triggering a run")

    existing_result = await db.execute(
        select(Run)
        .where(
            Run.user_id == current_user.id,
            Run.mode == requested_mode,
            Run.status.in_(["pending", "claimed", "scraping", "ranking"]),
        )
        .order_by(Run.started_at.desc())
    )
    existing_run = next(
        (
            run for run in existing_result.scalars().all()
            if bool((run.progress or {}).get("disable_scraping", False)) == disable_scraping
        ),
        None,
    )
    if existing_run:
        return {"run_id": existing_run.id, "status": existing_run.status}

    run = Run(
        user_id=current_user.id,
        status="pending",
        mode=requested_mode,
        trigger_source="manual",
        executor_type=executor_type,
        progress={
            "requested_mode": requested_mode,
            "force_scrape": False,
            "disable_scraping": disable_scraping,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    if api_runtime_flags()["run_api_worker"]:
        queue = get_queue(requested_mode)
        await queue.put(
            RunRequest(
                run.id,
                current_user.id,
                requested_mode,
                False,
                disable_scraping,
            )
        )
        logger.info("Run %s queued in-process by API worker (mode=%s user_id=%s)", run.id, requested_mode, current_user.id)
    else:
        logger.info(
            "Run %s created as pending in DB (mode=%s user_id=%s); awaiting dedicated worker service",
            run.id,
            requested_mode,
            current_user.id,
        )

    return {"run_id": run.id, "status": "pending"}


@router.post("/trigger", status_code=202)
async def trigger_run(
    body: TriggerRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_mode = (body.mode if body else "quick")
    return await _create_run(
        requested_mode=requested_mode,
        disable_scraping=bool(body.disable_scraping) if body else False,
        executor_type=body.executor_type if body else None,
        current_user=current_user,
        db=db,
    )


@router.post("/rank-existing", status_code=202)
async def rank_existing_jobs(
    body: TriggerRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_mode = (body.mode if body else "quick")
    return await _create_run(
        requested_mode=requested_mode,
        disable_scraping=True,
        executor_type=body.executor_type if body else None,
        current_user=current_user,
        db=db,
    )


@router.get("/latest", response_model=RunResponse)
async def get_latest_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No runs found")
    _status = _display_status(run.status)
    return RunResponse(
        run_id=run.id,
        status=_status,
        job_count=run.job_count,
        scrape_count=run.scrape_count,
        progress=run.progress,
        jobs_snapshot=_jobs_snapshot(run.progress),
        error=run.error,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
    )


@router.get("", response_model=list[RunResponse])
async def list_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id)
        .order_by(Run.started_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [
        RunResponse(
            run_id=r.id,
            status=_display_status(r.status),
            job_count=r.job_count,
            scrape_count=r.scrape_count,
            progress=r.progress,
            jobs_snapshot=_jobs_snapshot(r.progress),
            error=r.error,
            started_at=str(r.started_at) if r.started_at else None,
            finished_at=str(r.finished_at) if r.finished_at else None,
        )
        for r in runs
    ]


@router.get("/{run_id}/status", response_model=RunResponse)
async def get_run_status(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.id == run_id, Run.user_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _status = _display_status(run.status)
    return RunResponse(
        run_id=run.id,
        status=_status,
        job_count=run.job_count,
        scrape_count=run.scrape_count,
        progress=run.progress,
        jobs_snapshot=_jobs_snapshot(run.progress),
        error=run.error,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
    )


@router.post("/{run_id}/stop", status_code=200)
async def stop_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.id == run_id, Run.user_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Can only cancel runs that are pending, scraping, or ranking
    cancellable_statuses = {"pending", "claimed", "scraping", "ranking"}
    if run.status not in cancellable_statuses:
        return {"stopped": False, "status": run.status, "message": f"Run is already {run.status}"}

    original_status = run.status
    values = {"cancel_requested": True}
    if original_status == "pending":
        values.update({"status": "cancelled", "finished_at": datetime.now(timezone.utc)})
    await db.execute(update(Run).where(Run.id == run_id).values(**values))
    await db.commit()

    return {"stopped": True, "status": "cancelled" if original_status == "pending" else "cancelling"}
