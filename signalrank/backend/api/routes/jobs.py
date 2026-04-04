from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Application, ArchivalQueue, JobRaw, JobResult, Run, User
from api.stats_cache import get_cached_stats, set_cached_stats
from api.timezone import format_datetime_local
from api.routes.admin import require_admin

ARCHIVAL_TIERS = {"tier_ss", "tier_s", "tier_a"}

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


async def warm_default_jobs_cache(db: AsyncSession, *, user_id: str, tz_name: str | None = None) -> None:
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == user_id, Run.status == "success")
        .order_by(Run.finished_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return

    cache_key = "::".join(
        [
            "jobs_list",
            str(user_id),
            str(run.id),
            "1",
            "10",
            "final_score",
            "desc",
            "",
            "True",
            "0",
            "",
            "all",
            "",
            "any",
            tz_name or "utc",
        ]
    )
    if get_cached_stats(cache_key) is not None:
        return

    payload = await list_jobs(
        request=type("Request", (), {"headers": {"X-User-Timezone": tz_name}})(),
        page=1,
        limit=10,
        sort="final_score",
        sort_dir="desc",
        search="",
        show_archived=True,
        min_score=0,
        tiers=[],
        job_type="all",
        sites=[],
        date_range="any",
        current_user=type("User", (), {"id": user_id})(),
        db=db,
    )
    set_cached_stats(cache_key, payload)


@router.get("")
async def list_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sort: Literal["final_score", "semantic_score", "skills_score", "company_score", "seniority_score", "location_score", "recency_score", "title_relevance_score", "date_posted"] = Query("final_score"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
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
    tz_name = request.headers.get("X-User-Timezone")
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id, Run.status == "success")
        .order_by(Run.finished_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return {"jobs": [], "total": 0, "page": page, "limit": limit, "new_good_matches": 0}

    cache_key = "::".join(
        [
            "jobs_list",
            str(current_user.id),
            str(run.id),
            str(page),
            str(limit),
            sort,
            sort_dir,
            search,
            str(show_archived),
            str(min_score),
            ",".join(sorted(tiers)),
            job_type,
            ",".join(sorted(sites)),
            date_range,
            tz_name or "utc",
        ]
    )
    cached = get_cached_stats(cache_key)
    if cached is not None:
        return cached

    sort_col = JobRaw.date_posted if sort == "date_posted" else getattr(JobResult, sort)
    order_expr = sort_col.asc().nulls_last() if sort_dir == "asc" else sort_col.desc().nulls_last()

    base_filters = [JobResult.user_id == current_user.id]
    run_total = run.job_count or 0

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

    new_good_matches_result = await db.execute(
        select(func.count())
        .select_from(JobResult)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(
            JobResult.run_id == run.id,
            JobResult.user_id == current_user.id,
            JobResult.final_score >= 70,
            JobRaw.ingested_at >= run.started_at,
            ~JobResult.job_id.in_(
                select(Application.job_id).where(
                    Application.user_id == current_user.id,
                    Application.job_id.isnot(None),
                )
            ),
        )
    )
    new_good_matches = new_good_matches_result.scalar() or 0

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
        .order_by(order_expr)
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
            "date_posted": format_datetime_local(job.date_posted, tz_name),
            "is_new_find": bool(result.run_id == run.id and job.ingested_at and job.ingested_at >= run.started_at),
            "final_score": result.final_score / 100 if result.final_score is not None else None,
            "semantic_score": result.semantic_score,
            "skills_score": result.skills_score / 100 if result.skills_score is not None else None,
            "company_score": result.company_score / 100 if result.company_score is not None else None,
            "seniority_score": result.seniority_score / 100 if result.seniority_score is not None else None,
            "location_score": result.location_score / 100 if result.location_score is not None else None,
            "recency_score": result.recency_score / 100 if result.recency_score is not None else None,
            "title_relevance_score": result.title_relevance_score / 100 if result.title_relevance_score is not None else None,
            "fit_band": result.fit_band,
            "confidence_band": result.confidence_band,
            "explanation_summary": result.explanation_summary,
            "company_tier": result.company_tier if result.company_tier not in ("default", "", None) else None,
            "is_contract": result.is_contract,
            "archived_by_llm": result.archived_by_llm,
            "archival_reason": result.archival_reason,
        })

    payload = {
        "jobs": jobs,
        "total": total,
        "run_total": run_total,
        "available_sites": available_sites,
        "page": page,
        "limit": limit,
        "new_good_matches": new_good_matches,
    }
    set_cached_stats(cache_key, payload)
    return payload


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
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tz_name = request.headers.get("X-User-Timezone")
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id, Run.status == "success")
        .order_by(Run.finished_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return {"score_distribution": [], "top_companies": [], "sites": []}
    cache_key = f"jobs_analytics:{current_user.id}:{run.id}:{tz_name or 'utc'}"
    cached = get_cached_stats(cache_key)
    if cached is not None:
        return cached

    analytics = (
        await db.execute(
            text(
                """
                WITH filtered AS (
                    SELECT jr.final_score, j.company, j.site
                    FROM job_results jr
                    JOIN jobs_raw j ON j.id = jr.job_id
                    WHERE jr.run_id = :run_id AND jr.user_id = :user_id
                ),
                buckets(bucket, ord) AS (
                    VALUES
                        ('0-40', 1),
                        ('40-60', 2),
                        ('60-70', 3),
                        ('70-80', 4),
                        ('80-90', 5),
                        ('90-100', 6)
                ),
                score_counts AS (
                    SELECT
                        b.bucket,
                        b.ord,
                        COUNT(f.final_score) AS cnt
                    FROM buckets b
                    LEFT JOIN filtered f
                        ON (
                            (b.bucket = '0-40' AND f.final_score < 40) OR
                            (b.bucket = '40-60' AND f.final_score >= 40 AND f.final_score < 60) OR
                            (b.bucket = '60-70' AND f.final_score >= 60 AND f.final_score < 70) OR
                            (b.bucket = '70-80' AND f.final_score >= 70 AND f.final_score < 80) OR
                            (b.bucket = '80-90' AND f.final_score >= 80 AND f.final_score < 90) OR
                            (b.bucket = '90-100' AND f.final_score >= 90)
                        )
                    GROUP BY b.bucket, b.ord
                ),
                company_counts AS (
                    SELECT company, COUNT(*) AS cnt
                    FROM filtered
                    WHERE company IS NOT NULL
                    GROUP BY company
                    ORDER BY cnt DESC, company
                    LIMIT 10
                ),
                site_counts AS (
                    SELECT site, COUNT(*) AS cnt
                    FROM filtered
                    WHERE site IS NOT NULL
                    GROUP BY site
                    ORDER BY cnt DESC, site
                )
                SELECT
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object('range', bucket, 'count', cnt)
                                ORDER BY ord
                            )
                            FROM score_counts
                        ),
                        '[]'::json
                    ) AS score_distribution,
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object('company', company, 'count', cnt)
                                ORDER BY cnt DESC, company
                            )
                            FROM company_counts
                        ),
                        '[]'::json
                    ) AS top_companies,
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object('site', site, 'count', cnt)
                                ORDER BY cnt DESC, site
                            )
                            FROM site_counts
                        ),
                        '[]'::json
                    ) AS sites,
                    (SELECT COUNT(*) FROM filtered) AS total
                """
            ),
            {"run_id": run.id, "user_id": current_user.id},
        )
    ).mappings().one()

    payload = {
        "score_distribution": analytics["score_distribution"] or [],
        "top_companies": analytics["top_companies"] or [],
        "sites": analytics["sites"] or [],
        "total": analytics["total"] or 0,
    }
    set_cached_stats(cache_key, payload)
    return payload


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tz_name = request.headers.get("X-User-Timezone")
    result = await db.execute(
        select(JobResult, JobRaw)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(JobRaw.id == job_id, JobResult.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job_result, job = row
    return {
        "id": job.id,
        "job_url": job.job_url,
        "title": job.title,
        "company": job.company,
        "description": job.description,
        "location": job.location,
        "site": job.site,
        "date_posted": format_datetime_local(job.date_posted, tz_name),
        "fit_band": job_result.fit_band,
        "confidence_band": job_result.confidence_band,
        "explanation_summary": job_result.explanation_summary,
    }
