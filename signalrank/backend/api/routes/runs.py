from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Run, User
from batch.worker import get_queue

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunResponse(BaseModel):
    run_id: str
    status: str
    job_count: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


@router.post("/trigger", status_code=202)
async def trigger_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = Run(user_id=current_user.id, status="pending")
    db.add(run)
    await db.commit()
    await db.refresh(run)

    queue = get_queue()
    await queue.put((run.id, current_user.id))

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
    return RunResponse(
        run_id=run.id,
        status=run.status,
        job_count=run.job_count,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
    )


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
    return RunResponse(
        run_id=run.id,
        status=run.status,
        job_count=run.job_count,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
    )
