from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import api_runtime_flags
from api.database import get_db
from api.deps import get_current_user
from api.models import Profile, Run, User
from batch.worker import get_queue

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunResponse(BaseModel):
    run_id: str
    status: str
    job_count: int | None = None
    scrape_count: int | None = None
    progress: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None


class TriggerRunRequest(BaseModel):
    mode: Literal["quick", "full"] = "quick"


@router.post("/trigger", status_code=202)
async def trigger_run(
    body: TriggerRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_mode = (body.mode if body else "quick")
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.onboarding_complete:
        raise HTTPException(status_code=400, detail="Please complete onboarding before triggering a run")

    run = Run(
        user_id=current_user.id,
        status="pending",
        progress={"requested_mode": requested_mode, "force_scrape": False},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    if api_runtime_flags()["run_api_worker"]:
        queue = get_queue()
        await queue.put((run.id, current_user.id, requested_mode, False))

    return {"run_id": run.id, "status": "pending"}


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
    _status = "done" if run.status == "success" else run.status
    return RunResponse(
        run_id=run.id,
        status=_status,
        job_count=run.job_count,
        scrape_count=run.scrape_count,
        progress=run.progress,
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
            status="done" if r.status == "success" else r.status,
            job_count=r.job_count,
            scrape_count=r.scrape_count,
            progress=r.progress,
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
    _status = "done" if run.status == "success" else run.status
    return RunResponse(
        run_id=run.id,
        status=_status,
        job_count=run.job_count,
        scrape_count=run.scrape_count,
        progress=run.progress,
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
    cancellable_statuses = {"pending", "scraping", "ranking"}
    if run.status not in cancellable_statuses:
        return {"stopped": False, "status": run.status, "message": f"Run is already {run.status}"}

    # If run is pending (queued but not started), we need to try to remove it from the queue
    # If run is already processing, we mark it as cancelled in the DB; the worker will check
    await db.execute(
        update(Run).where(Run.id == run_id).values(status="cancelled", finished_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return {"stopped": True, "status": "cancelled"}
