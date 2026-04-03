from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import api_runtime_flags
from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from batch.resume_worker import force_regenerate_all
from batch.quality_report import compute_global_quality_metrics, compute_user_quality_metrics
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
    stats = (
        await db.execute(
            select(
                select(func.count(User.id)).scalar_subquery().label("total_users"),
                select(func.count(JobRaw.id)).scalar_subquery().label("total_jobs"),
                select(func.count(Run.id)).scalar_subquery().label("total_runs"),
                select(func.count(Application.id)).scalar_subquery().label("total_applications"),
            )
        )
    ).one()
    return AdminStatsResponse(
        total_users=stats.total_users or 0,
        total_jobs=stats.total_jobs or 0,
        total_runs=stats.total_runs or 0,
        total_applications=stats.total_applications or 0,
    )


@router.get("/users")
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    total_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    users_result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    users = users_result.scalars().all()
    if not users:
        return {"users": [], "total": total_count, "limit": limit, "offset": offset}

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

    user_list = [
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
    return {"users": user_list, "total": total_count, "limit": limit, "offset": offset}


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
    title_relevance_score: float | None
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
                jr.title_relevance_score, j.title, j.company, j.location, j.job_url
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
            title_relevance_score=r["title_relevance_score"],
            job_url=r["job_url"],
        )
        for r in sorted(rows, key=lambda x: (x["final_score"] or 0), reverse=True)[:10]
    ]


class TriggerRunRequest(BaseModel):
    mode: str = "full"
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
    mode = body.mode if body.mode in ("quick", "full") else "full"
    run = Run(
        user_id=user.id,
        status="pending",
        mode=mode,
        progress={"requested_mode": mode, "force_scrape": body.force_scrape},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    if api_runtime_flags()["run_api_worker"]:
        queue = get_queue(mode)
        await queue.put(RunRequest(run.id, user.id, mode, body.force_scrape))
    return {"run_id": run.id, "status": "pending", "mode": mode, "user_email": user.email}


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


@router.post("/users/{user_id}/force-regenerate-resumes", status_code=202)
async def force_regenerate_resumes_for_user(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await force_regenerate_all(db, user_id)
    return {"queued": count, "user_id": user_id}


@router.post("/users/{user_id}/reparse-resume", status_code=202)
async def reparse_resume_for_user(
    user_id: str,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-run LLM resume parse + verify pipeline for a single user.

    Uses stored resume_text (no PDF required). Applies latest verifier fixes
    (ligature normalisation, inverted-caps, date correction, hallucination removal).
    """
    from api.routes.onboarding import _parse_and_update_profile

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not (profile.resume_text or "").strip():
        raise HTTPException(status_code=404, detail="User has no resume text stored")

    llm = get_llm_client()
    background_tasks.add_task(
        _parse_and_update_profile, user_id, profile.resume_text, llm
    )
    return {"status": "queued", "user_id": user_id}


@router.get("/quality-metrics")
async def get_global_quality_metrics(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    k: int = Query(default=10, ge=1, le=50),
):
    return await compute_global_quality_metrics(db, k=k)


@router.get("/quality-metrics/{user_id}")
async def get_user_quality_metrics(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    k: int = Query(default=10, ge=1, le=50),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await compute_user_quality_metrics(db, user_id, k=k)


@router.post("/reparse-all-resumes", status_code=202)
async def reparse_all_resumes(
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-run LLM resume parse + verify pipeline for every user who has resume text.

    Fires all parses as background tasks.  Returns count of users queued.
    Each user's resume_editor, skills, distilled_text, and target_roles are
    updated in-place; onboarding_complete is left unchanged.
    """
    from api.routes.onboarding import _parse_and_update_profile

    result = await db.execute(
        select(Profile.user_id, Profile.resume_text).where(
            Profile.resume_text.is_not(None),
            Profile.resume_text != "",
        )
    )
    rows = result.all()
    llm = get_llm_client()
    for user_id, resume_text in rows:
        background_tasks.add_task(
            _parse_and_update_profile, user_id, resume_text, llm
        )
    return {"queued": len(rows)}
