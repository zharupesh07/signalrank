from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import (
    Application, ArchivalQueue, GenerationQueue, JobRaw, JobResult,
    Profile, RecruiterRefreshTask, Run, TailoredResume, User,
)
from batch.worker import get_queue

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class AdminUserResponse(BaseModel):
    id: str
    email: str
    is_admin: bool
    created_at: str
    last_login: str | None
    onboarding_complete: bool
    run_count: int
    last_run_status: str | None


class AdminStatsResponse(BaseModel):
    total_users: int
    total_jobs: int
    total_runs: int
    total_applications: int


class AdminRunResponse(BaseModel):
    run_id: str
    user_email: str
    status: str
    job_count: int | None
    started_at: str | None
    finished_at: str | None


class UpdateUserRequest(BaseModel):
    is_admin: bool | None = None


@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(func.count(User.id))).scalar() or 0
    jobs = (await db.execute(func.count(JobRaw.id))).scalar() or 0
    runs = (await db.execute(func.count(Run.id))).scalar() or 0
    apps = (await db.execute(func.count(Application.id))).scalar() or 0
    return AdminStatsResponse(
        total_users=users, total_jobs=jobs, total_runs=runs, total_applications=apps
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Fetch all users
    users_result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = users_result.scalars().all()
    if not users:
        return []

    user_ids = [u.id for u in users]

    # Batch fetch profiles
    profiles_result = await db.execute(
        select(Profile).where(Profile.user_id.in_(user_ids))
    )
    profiles_by_user = {p.user_id: p for p in profiles_result.scalars().all()}

    # Batch fetch run counts
    run_counts_result = await db.execute(
        select(Run.user_id, func.count(Run.id).label("cnt"))
        .where(Run.user_id.in_(user_ids))
        .group_by(Run.user_id)
    )
    run_counts = {row.user_id: row.cnt for row in run_counts_result.all()}

    # Batch fetch latest run per user using a subquery
    latest_run_sq = (
        select(Run.user_id, func.max(Run.started_at).label("max_started"))
        .where(Run.user_id.in_(user_ids))
        .group_by(Run.user_id)
        .subquery()
    )
    latest_runs_result = await db.execute(
        select(Run).join(
            latest_run_sq,
            (Run.user_id == latest_run_sq.c.user_id)
            & (Run.started_at == latest_run_sq.c.max_started),
        )
    )
    latest_runs = {r.user_id: r for r in latest_runs_result.scalars().all()}

    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            is_admin=u.is_admin,
            created_at=str(u.created_at),
            last_login=str(u.last_login) if u.last_login else None,
            onboarding_complete=profiles_by_user[u.id].onboarding_complete
                if u.id in profiles_by_user else False,
            run_count=run_counts.get(u.id, 0),
            last_run_status=latest_runs[u.id].status if u.id in latest_runs else None,
        )
        for u in users
    ]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    await db.commit()
    return {"status": "updated"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.execute(delete(ArchivalQueue).where(ArchivalQueue.user_id == user_id))
    await db.execute(delete(GenerationQueue).where(GenerationQueue.user_id == user_id))
    await db.execute(delete(TailoredResume).where(TailoredResume.user_id == user_id))
    await db.execute(delete(RecruiterRefreshTask).where(RecruiterRefreshTask.user_id == user_id))
    await db.execute(delete(JobResult).where(JobResult.user_id == user_id))
    await db.execute(delete(Run).where(Run.user_id == user_id))
    await db.execute(delete(Application).where(Application.user_id == user_id))
    await db.execute(delete(Profile).where(Profile.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return {"status": "deleted"}


@router.post("/users/{user_id}/trigger-run", status_code=202)
async def trigger_run_for_user(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    run = Run(user_id=user.id, status="pending")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    queue = get_queue()
    await queue.put((run.id, user.id))
    return {"run_id": run.id, "status": "pending", "user_email": user.email}


@router.get("/runs", response_model=list[AdminRunResponse])
async def list_all_runs(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run, User.email)
        .join(User, Run.user_id == User.id)
        .order_by(Run.started_at.desc())
        .limit(100)
    )
    rows = result.all()
    return [
        AdminRunResponse(
            run_id=r.id,
            user_email=email,
            status=r.status,
            job_count=r.job_count,
            started_at=str(r.started_at) if r.started_at else None,
            finished_at=str(r.finished_at) if r.finished_at else None,
        )
        for r, email in rows
    ]
