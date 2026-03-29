from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import ArchivalQueue, JobRaw, JobResult, Run, User
from api.routes.admin import require_admin

ARCHIVAL_TIERS = {"tier_ss", "tier_s", "tier_a"}

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort: Literal["final_score", "semantic_score", "skills_score", "company_score", "seniority_score", "location_score", "recency_score"] = Query("final_score"),
    search: str = Query(""),
    show_archived: bool = Query(True),
    min_score: int = Query(0, ge=0, le=100),
    tiers: list[str] = Query(default=[]),
    job_type: Literal["all", "fte", "contract"] = Query("all"),
    sites: list[str] = Query(default=[]),
    date_range: Literal["any", "24h", "week", "month"] = Query("any"),
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

    sort_col = getattr(JobResult, sort)

    base_filters = [JobResult.run_id == run.id, JobResult.user_id == current_user.id]
    run_total_query = select(func.count()).select_from(JobResult).where(*base_filters)
    run_total = (await db.execute(run_total_query)).scalar() or 0

    if not show_archived:
        base_filters.append(
            or_(JobResult.archived_by_llm.is_(None), JobResult.archived_by_llm == False)
        )
    if search:
        pattern = f"%{search}%"
        base_filters.append(
            or_(JobRaw.title.ilike(pattern), JobRaw.company.ilike(pattern))
        )

    if min_score > 0:
        base_filters.append(JobResult.final_score >= min_score)

    if tiers:
        normalized_tiers = [tier for tier in tiers if tier and tier != "unknown"]
        wants_unknown = "unknown" in tiers
        tier_clauses = []
        if normalized_tiers:
            tier_clauses.append(JobResult.company_tier.in_(normalized_tiers))
        if wants_unknown:
            tier_clauses.append(JobResult.company_tier.is_(None))
            tier_clauses.append(JobResult.company_tier.in_(["default", ""]))
        if tier_clauses:
            base_filters.append(or_(*tier_clauses))

    if job_type == "contract":
        base_filters.append(JobResult.is_contract.is_(True))
    elif job_type == "fte":
        base_filters.append(or_(JobResult.is_contract.is_(False), JobResult.is_contract.is_(None)))

    if date_range != "any":
        hours = {"24h": 24, "week": 24 * 7, "month": 24 * 30}[date_range]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        base_filters.append(JobRaw.date_posted.is_not(None))
        base_filters.append(JobRaw.date_posted >= cutoff)

    site_filters = list(base_filters)
    if sites:
        site_filters.append(JobRaw.site.in_(sites))

    count_query = select(func.count()).select_from(JobResult).join(JobRaw, JobResult.job_id == JobRaw.id).where(*site_filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    sites_query = await db.execute(
        select(JobRaw.site)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(*base_filters, JobRaw.site.is_not(None))
        .distinct()
        .order_by(JobRaw.site.asc())
    )
    available_sites = [site for site in sites_query.scalars().all() if site]

    results = await db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(*site_filters)
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

    return {
        "jobs": jobs,
        "total": total,
        "run_total": run_total,
        "available_sites": available_sites,
        "page": page,
        "limit": limit,
    }


@router.post("/archive-unsuitable", status_code=200)
async def archive_unsuitable(
    current_user: User = Depends(require_admin),
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
    current_user: User = Depends(require_admin),
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

    from sqlalchemy import case, literal_column

    base = [JobResult.run_id == run.id, JobResult.user_id == current_user.id]

    score_q = await db.execute(
        select(
            case(
                (JobResult.final_score < 40, literal_column("'0-40'")),
                (JobResult.final_score < 60, literal_column("'40-60'")),
                (JobResult.final_score < 70, literal_column("'60-70'")),
                (JobResult.final_score < 80, literal_column("'70-80'")),
                (JobResult.final_score < 90, literal_column("'80-90'")),
                else_=literal_column("'90-100'"),
            ).label("bucket"),
            func.count().label("cnt"),
        ).where(*base).group_by("bucket")
    )
    bucket_rows = {r.bucket: r.cnt for r in score_q.all()}
    score_distribution = [
        {"range": k, "count": bucket_rows.get(k, 0)}
        for k in ("0-40", "40-60", "60-70", "70-80", "80-90", "90-100")
    ]

    company_q = await db.execute(
        select(JobRaw.company, func.count().label("cnt"))
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(*base, JobRaw.company.isnot(None))
        .group_by(JobRaw.company)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_companies = [{"company": r.company, "count": r.cnt} for r in company_q.all()]

    site_q = await db.execute(
        select(JobRaw.site, func.count().label("cnt"))
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(*base, JobRaw.site.isnot(None))
        .group_by(JobRaw.site)
        .order_by(func.count().desc())
    )
    sites = [{"site": r.site, "count": r.cnt} for r in site_q.all()]

    total_q = await db.execute(select(func.count()).where(*base))
    total_jobs = total_q.scalar() or 0

    return {
        "score_distribution": score_distribution,
        "top_companies": top_companies,
        "sites": sites,
        "total": total_jobs,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobRaw)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(JobRaw.id == job_id, JobResult.user_id == current_user.id)
    )
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
