from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import ArchivalQueue, JobRaw, JobResult, Run, User

ARCHIVAL_TIERS = {"tier_ss", "tier_s", "tier_a"}

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=5000),
    sort: str = Query("final_score"),
    search: str = Query(""),
    show_archived: bool = Query(True),
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

    base_filters = [JobResult.run_id == run.id, JobResult.user_id == current_user.id]
    if not show_archived:
        base_filters.append(
            or_(JobResult.archived_by_llm.is_(None), JobResult.archived_by_llm == False)
        )
    if search:
        pattern = f"%{search}%"
        base_filters.append(
            or_(JobRaw.title.ilike(pattern), JobRaw.company.ilike(pattern))
        )

    count_query = select(func.count()).select_from(JobResult).join(JobRaw, JobResult.job_id == JobRaw.id).where(*base_filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    results = await db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(*base_filters)
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
            "final_score": result.final_score / 100 if result.final_score is not None else None,
            "semantic_score": result.semantic_score,
            "skills_score": result.skills_score / 100 if result.skills_score is not None else None,
            "company_score": result.company_score / 100 if result.company_score is not None else None,
            "seniority_score": result.seniority_score / 100 if result.seniority_score is not None else None,
            "location_score": result.location_score / 100 if result.location_score is not None else None,
            "recency_score": result.recency_score / 100 if result.recency_score is not None else None,
            "company_tier": result.company_tier if result.company_tier not in ("default", "", None) else None,
            "is_contract": result.is_contract,
            "archived_by_llm": result.archived_by_llm,
            "archival_reason": result.archival_reason,
        })

    return {"jobs": jobs, "total": total, "page": page, "limit": limit}


@router.post("/archive-unsuitable", status_code=200)
async def archive_unsuitable(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue all unevaluated SS/S/A tier JobResults for LLM archival evaluation."""
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id, Run.status == "success")
        .order_by(Run.finished_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return {"queued": 0, "message": "No successful run found"}

    results = await db.execute(
        select(JobResult.id)
        .where(
            JobResult.run_id == run.id,
            JobResult.user_id == current_user.id,
            JobResult.archived_by_llm.is_(None),
            JobResult.company_tier.in_(ARCHIVAL_TIERS),
        )
    )
    job_result_ids = [r[0] for r in results.all()]

    if not job_result_ids:
        return {"queued": 0, "message": "All eligible jobs already evaluated"}

    await db.execute(
        pg_insert(ArchivalQueue)
        .values([
            {"user_id": current_user.id, "job_result_id": jrid}
            for jrid in job_result_ids
        ])
        .on_conflict_do_nothing(constraint="uq_archival_queue_user_job_result")
    )
    await db.commit()

    return {"queued": len(job_result_ids)}


@router.get("/archive-status")
async def archive_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return progress of archival evaluation for the current user."""
    result = await db.execute(
        select(
            ArchivalQueue.status,
            func.count(ArchivalQueue.id),
        )
        .where(ArchivalQueue.user_id == current_user.id)
        .group_by(ArchivalQueue.status)
    )
    counts = {row[0]: row[1] for row in result.all()}
    total = sum(counts.values())

    return {
        "total": total,
        "done": counts.get("done", 0),
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "failed": counts.get("failed", 0),
    }


@router.get("/analytics")
async def get_analytics(
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
        return {"score_distribution": [], "top_companies": [], "sites": []}

    results = await db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(JobResult.run_id == run.id, JobResult.user_id == current_user.id)
    )
    rows = results.all()

    score_buckets = {"0-40": 0, "40-60": 0, "60-70": 0, "70-80": 0, "80-90": 0, "90-100": 0}
    company_counts: dict[str, int] = {}
    site_counts: dict[str, int] = {}

    for result, job in rows:
        score = result.final_score or 0
        if score < 40:
            score_buckets["0-40"] += 1
        elif score < 60:
            score_buckets["40-60"] += 1
        elif score < 70:
            score_buckets["60-70"] += 1
        elif score < 80:
            score_buckets["70-80"] += 1
        elif score < 90:
            score_buckets["80-90"] += 1
        else:
            score_buckets["90-100"] += 1

        if job.company:
            company_counts[job.company] = company_counts.get(job.company, 0) + 1
        if job.site:
            site_counts[job.site] = site_counts.get(job.site, 0) + 1

    top_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    sites = sorted(site_counts.items(), key=lambda x: x[1], reverse=True)

    total_jobs = await db.scalar(select(func.count(JobRaw.id)))

    return {
        "score_distribution": [{"range": k, "count": v} for k, v in score_buckets.items()],
        "top_companies": [{"company": c, "count": n} for c, n in top_companies],
        "sites": [{"site": s, "count": n} for s, n in sites],
        "total": total_jobs or 0,
    }


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
