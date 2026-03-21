from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import JobRaw, JobResult, Run, User

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query("final_score"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id, Run.status == "success")
        .order_by(Run.finished_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return {"jobs": [], "total": 0, "page": page, "limit": limit}

    sort_col = getattr(JobResult, sort, JobResult.final_score)

    total_result = await db.execute(
        select(func.count()).where(JobResult.run_id == run.id, JobResult.user_id == current_user.id)
    )
    total = total_result.scalar()

    results = await db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(JobResult.run_id == run.id, JobResult.user_id == current_user.id)
        .order_by(sort_col.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = results.all()

    jobs = []
    for result, job in rows:
        jobs.append({
            "id": job.id,
            "job_url": job.job_url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "site": job.site,
            "date_posted": str(job.date_posted) if job.date_posted else None,
            "final_score": result.final_score,
            "semantic_score": result.semantic_score,
            "skills_score": result.skills_score,
            "company_score": result.company_score,
            "seniority_score": result.seniority_score,
            "location_score": result.location_score,
            "recency_score": result.recency_score,
            "company_tier": result.company_tier,
            "is_contract": result.is_contract,
        })

    return {"jobs": jobs, "total": total, "page": page, "limit": limit}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(JobRaw).where(JobRaw.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "job_url": job.job_url,
        "title": job.title,
        "company": job.company,
        "description": job.description,
        "location": job.location,
        "site": job.site,
        "date_posted": str(job.date_posted) if job.date_posted else None,
    }
