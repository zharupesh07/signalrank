from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import api_runtime_flags
from api.database import get_db
from api.deps import get_current_user
from api.models import (
    Application, ArchivalQueue, GenerationQueue, JobRaw, JobResult,
    Profile, RecruiterRefreshTask, Run, TailoredResume, User,
)
from batch.worker import RunRequest, get_queue

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


class ResetProfileJobsResponse(BaseModel):
    status: str
    user_email: str
    runs_deleted: int
    job_results_deleted: int
    generation_queue_deleted: int
    tailored_resumes_deleted: int
    archival_queue_deleted: int
    jobs_preserved: bool = True


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


@router.post("/users/{user_id}/reset-jobs", response_model=ResetProfileJobsResponse)
async def reset_jobs_for_user(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    archival_deleted = (
        await db.execute(delete(ArchivalQueue).where(ArchivalQueue.user_id == user_id))
    ).rowcount or 0
    generation_deleted = (
        await db.execute(delete(GenerationQueue).where(GenerationQueue.user_id == user_id))
    ).rowcount or 0
    tailored_deleted = (
        await db.execute(delete(TailoredResume).where(TailoredResume.user_id == user_id))
    ).rowcount or 0
    job_results_deleted = (
        await db.execute(delete(JobResult).where(JobResult.user_id == user_id))
    ).rowcount or 0
    runs_deleted = (
        await db.execute(delete(Run).where(Run.user_id == user_id))
    ).rowcount or 0

    await db.commit()
    return ResetProfileJobsResponse(
        status="reset",
        user_email=user.email,
        runs_deleted=runs_deleted,
        job_results_deleted=job_results_deleted,
        generation_queue_deleted=generation_deleted,
        tailored_resumes_deleted=tailored_deleted,
        archival_queue_deleted=archival_deleted,
    )


class TopJob(BaseModel):
    job_id: str
    title: str | None
    company: str | None
    location: str | None
    final_score: float | None
    semantic_score: float | None
    skills_score: float | None
    job_url: str


@router.get("/users/{user_id}/top-jobs", response_model=list[TopJob])
async def get_user_top_jobs(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            SELECT DISTINCT ON (jr.job_id)
                jr.job_id, jr.semantic_score, jr.skills_score, jr.final_score,
                j.title, j.company, j.location, j.job_url
            FROM job_results jr
            JOIN jobs_raw j ON jr.job_id = j.id
            WHERE jr.user_id = :user_id
            ORDER BY jr.job_id, jr.final_score DESC NULLS LAST
        """),
        {"user_id": user_id},
    )
    rows = result.mappings().all()
    return [
        TopJob(
            job_id=str(r["job_id"]),
            title=r["title"],
            company=r["company"],
            location=r["location"],
            final_score=r["final_score"],
            semantic_score=r["semantic_score"],
            skills_score=r["skills_score"],
            job_url=r["job_url"],
        )
        for r in sorted(rows, key=lambda x: (x["final_score"] or 0), reverse=True)[:10]
    ]


class TriggerRunRequest(BaseModel):
    force_scrape: bool = False


@router.post("/users/{user_id}/trigger-run", status_code=202)
async def trigger_run_for_user(
    user_id: str,
    body: TriggerRunRequest = TriggerRunRequest(),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    run = Run(
        user_id=user.id,
        status="pending",
        progress={"requested_mode": "full", "force_scrape": body.force_scrape},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    if api_runtime_flags()["run_api_worker"]:
        queue = get_queue()
        await queue.put(RunRequest(run.id, user.id, "full", body.force_scrape))
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
