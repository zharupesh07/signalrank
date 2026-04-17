from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.utils import deep_merge_dict, profile_resume_template
from api.deps_llm import get_llm_client
from api.stats_cache import get_cached_stats, invalidate_stats_cache, set_cached_stats
from batch.context import deep_merge, load_base_config
from batch.scrape_cache import normalize_cache_value
from batch.maintenance import prune_current_session, prune_once
from batch.resume_worker import force_regenerate_all
from batch.quality_report import compute_global_quality_metrics, compute_user_quality_metrics
from batch.run_kinds import run_kind_from_flags
from batch.run_progress import progress_int, progress_str
from api.models import (
    Application, ArchivalQueue, GenerationQueue, JobRaw, JobResult, QueryPlanCache, ScrapeQueryCache,
    Profile, RecruiterRefreshTask, Run, TailoredResume, User,
)
from domain.profile_rules import enrich_config_with_profile_rules

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
    scrape_count: int | None = None
    corpus_count: int | None = None
    scored_count: int | None = None
    shown_count: int | None = None
    corpus_source: str | None = None
    run_kind: str | None = None
    scrape_reason: str | None = None
    started_at: str | None
    finished_at: str | None


class AdminStopRunResponse(BaseModel):
    stopped: bool
    status: str
    message: str | None = None


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


class AdminUserProfileConfigResponse(BaseModel):
    user_id: str
    email: str
    onboarding_complete: bool
    target_roles: list[str]
    preferred_locations: list[str]
    custom_search_queries: list[str]
    target_lpa: float | None
    min_yoe: int | None
    max_yoe: int | None
    scraper_hours_old: int | None
    scraper_max_terms: int | None
    resume_template: str | None
    config_overrides: dict | None
    title_penalty_rules: dict[str, list[str]]


class AdminUserProfileConfigUpdate(BaseModel):
    onboarding_complete: bool | None = None
    target_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    custom_search_queries: list[str] | None = None
    target_lpa: float | None = None
    min_yoe: int | None = None
    max_yoe: int | None = None
    scraper_hours_old: int | None = None
    scraper_max_terms: int | None = None
    resume_template: str | None = None
    config_overrides: dict | None = None



@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cache_key = "admin_stats"
    cached = get_cached_stats(cache_key)
    if cached is not None:
        return cached
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
    payload = AdminStatsResponse(
        total_users=stats.total_users or 0,
        total_jobs=stats.total_jobs or 0,
        total_runs=stats.total_runs or 0,
        total_applications=stats.total_applications or 0,
    )
    set_cached_stats(cache_key, payload)
    return payload


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
    invalidate_stats_cache("admin_stats")
    return {"status": "updated"}


@router.get("/users/{user_id}/profile-config", response_model=AdminUserProfileConfigResponse)
async def get_user_profile_config(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    return AdminUserProfileConfigResponse(
        user_id=user.id,
        email=user.email,
        onboarding_complete=profile.onboarding_complete if profile else False,
        target_roles=list(profile.target_roles or []) if profile else [],
        preferred_locations=list(profile.preferred_locations or []) if profile else [],
        custom_search_queries=list(profile.custom_search_queries or []) if profile else [],
        target_lpa=profile.target_lpa if profile else None,
        min_yoe=profile.min_yoe if profile else None,
        max_yoe=profile.max_yoe if profile else None,
        scraper_hours_old=profile.scraper_hours_old if profile else None,
        scraper_max_terms=profile.scraper_max_terms if profile else None,
        resume_template=profile_resume_template(profile),
        config_overrides=dict(profile.config_overrides or {}) if profile else None,
        title_penalty_rules=(
            enrich_config_with_profile_rules(
                deep_merge(load_base_config(), dict(profile.config_overrides or {})) if profile and isinstance(profile.config_overrides, dict) else load_base_config(),
                resume_text=profile.resume_text if profile else "",
                profile_roles=profile.target_roles if profile else [],
            ).get("ranking", {}).get("profile_title_rules", {"strong": [], "adjacent": [], "hybrid": []})
        ),
    )


@router.patch("/users/{user_id}/profile-config")
async def update_user_profile_config(
    user_id: str,
    body: AdminUserProfileConfigUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id).with_for_update()
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.flush()

    payload = body.model_dump(exclude_unset=True)
    resume_template = payload.pop("resume_template", None) if "resume_template" in payload else None
    config_overrides = payload.pop("config_overrides", None) if "config_overrides" in payload else None

    for field, value in payload.items():
        setattr(profile, field, value)

    if config_overrides is not None:
        profile.config_overrides = deep_merge_dict(profile.config_overrides, config_overrides)

    if "resume_template" in body.model_fields_set:
        profile.config_overrides = deep_merge_dict(
            profile.config_overrides,
            {"resume": {"template": resume_template}},
        )

    await db.commit()
    invalidate_stats_cache("admin_stats")
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
    invalidate_stats_cache("admin_stats")
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
    invalidate_stats_cache("admin_stats")
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
    disable_scraping: bool = False
    auto_refresh: bool = False


class MaintenanceResponse(BaseModel):
    deleted: dict[str, int]


class CacheSummaryResponse(BaseModel):
    scrape_query_cache_count: int
    query_plan_cache_count: int
    sample_scrape_query_keys: list[dict]
    sample_query_plan_keys: list[dict]


class CacheInvalidateRequest(BaseModel):
    kind: Literal["scrape_query_cache", "query_plan_cache"]
    clear_all: bool = False
    provider: str | None = None
    site: str | None = None
    term: str | None = None
    location: str | None = None
    country: str | None = None
    hours_old: int | None = None
    profile_fingerprint: str | None = None
    search_window_days: int | None = None
    source_filter: str | None = None
    query_version: str | None = None


class CacheInvalidateResponse(BaseModel):
    kind: str
    deleted: int
    clear_all: bool


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
        progress={
            "requested_mode": mode,
            "force_scrape": body.force_scrape,
            "disable_scraping": body.disable_scraping,
            "auto_refresh": body.auto_refresh,
            "run_kind": run_kind_from_flags(
                force_scrape=body.force_scrape,
                disable_scraping=body.disable_scraping,
                auto_refresh=body.auto_refresh,
            ),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return {"run_id": run.id, "status": "pending", "mode": mode, "user_email": user.email}


@router.post("/maintenance/prune", response_model=MaintenanceResponse)
async def trigger_maintenance_prune(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    summary = await prune_current_session(db)
    return MaintenanceResponse(deleted=summary.deleted)


@router.get("/caches", response_model=CacheSummaryResponse)
async def list_caches(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scrape_count = (await db.execute(select(func.count()).select_from(ScrapeQueryCache))).scalar_one() or 0
    query_plan_count = (await db.execute(select(func.count()).select_from(QueryPlanCache))).scalar_one() or 0
    scrape_rows = (
        await db.execute(
            select(
                ScrapeQueryCache.provider,
                ScrapeQueryCache.site,
                ScrapeQueryCache.term_normalized,
                ScrapeQueryCache.location_normalized,
                ScrapeQueryCache.country_normalized,
                ScrapeQueryCache.hours_old,
                ScrapeQueryCache.result_count,
                ScrapeQueryCache.fresh_until,
            )
            .order_by(ScrapeQueryCache.searched_at.desc())
            .limit(20)
        )
    ).all()
    plan_rows = (
        await db.execute(
            select(
                QueryPlanCache.profile_fingerprint,
                QueryPlanCache.search_window_days,
                QueryPlanCache.source_filter,
                QueryPlanCache.query_version,
                QueryPlanCache.max_terms,
                QueryPlanCache.created_at,
            )
            .order_by(QueryPlanCache.updated_at.desc())
            .limit(20)
        )
    ).all()
    return CacheSummaryResponse(
        scrape_query_cache_count=int(scrape_count),
        query_plan_cache_count=int(query_plan_count),
        sample_scrape_query_keys=[
            {
                "provider": row.provider,
                "site": row.site,
                "term": row.term_normalized,
                "location": row.location_normalized,
                "country": row.country_normalized,
                "hours_old": row.hours_old,
                "result_count": row.result_count,
                "fresh_until": str(row.fresh_until) if row.fresh_until else None,
            }
            for row in scrape_rows
        ],
        sample_query_plan_keys=[
            {
                "profile_fingerprint": row.profile_fingerprint,
                "search_window_days": row.search_window_days,
                "source_filter": row.source_filter,
                "query_version": row.query_version,
                "max_terms": row.max_terms,
                "created_at": str(row.created_at) if row.created_at else None,
            }
            for row in plan_rows
        ],
    )


@router.post("/caches/invalidate", response_model=CacheInvalidateResponse)
async def invalidate_cache(
    body: CacheInvalidateRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    deleted = 0
    if body.kind == "scrape_query_cache":
        stmt = delete(ScrapeQueryCache)
        if not body.clear_all:
            clauses = []
            if body.provider:
                clauses.append(ScrapeQueryCache.provider == body.provider)
            if body.site:
                clauses.append(ScrapeQueryCache.site == body.site)
            if body.term:
                clauses.append(ScrapeQueryCache.term_normalized == normalize_cache_value(body.term))
            if body.location:
                clauses.append(ScrapeQueryCache.location_normalized == normalize_cache_value(body.location))
            if body.country:
                clauses.append(ScrapeQueryCache.country_normalized == normalize_cache_value(body.country))
            if body.hours_old is not None:
                clauses.append(ScrapeQueryCache.hours_old == body.hours_old)
            if not clauses:
                raise HTTPException(status_code=400, detail="Provide clear_all or at least one scrape cache filter")
            for clause in clauses:
                stmt = stmt.where(clause)
        result = await db.execute(stmt)
        deleted = int(result.rowcount or 0)
    elif body.kind == "query_plan_cache":
        stmt = delete(QueryPlanCache)
        if not body.clear_all:
            clauses = []
            if body.profile_fingerprint:
                clauses.append(QueryPlanCache.profile_fingerprint == body.profile_fingerprint)
            if body.search_window_days is not None:
                clauses.append(QueryPlanCache.search_window_days == body.search_window_days)
            if body.source_filter:
                clauses.append(QueryPlanCache.source_filter == body.source_filter)
            if body.query_version:
                clauses.append(QueryPlanCache.query_version == body.query_version)
            if not clauses:
                raise HTTPException(status_code=400, detail="Provide clear_all or at least one query plan cache filter")
            for clause in clauses:
                stmt = stmt.where(clause)
        result = await db.execute(stmt)
        deleted = int(result.rowcount or 0)
    else:
        raise HTTPException(status_code=400, detail="Unsupported cache kind")

    await db.commit()
    return CacheInvalidateResponse(kind=body.kind, deleted=deleted, clear_all=body.clear_all)


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
            scrape_count=r.scrape_count,
            corpus_count=progress_int(r.progress, "corpus_job_count"),
            scored_count=progress_int(r.progress, "scored_job_count"),
            shown_count=progress_int(r.progress, "shown_job_count"),
            corpus_source=progress_str(r.progress, "corpus_source"),
            run_kind=str((r.progress or {}).get("run_kind")) if isinstance(r.progress, dict) and (r.progress or {}).get("run_kind") else None,
            scrape_reason=str((r.progress or {}).get("scrape_reason")) if isinstance(r.progress, dict) and (r.progress or {}).get("scrape_reason") else None,
            started_at=str(r.started_at) if r.started_at else None,
            finished_at=str(r.finished_at) if r.finished_at else None,
        )
        for r, email in rows
    ]


@router.post("/runs/{run_id}/stop", response_model=AdminStopRunResponse)
async def stop_run(
    run_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"pending", "scraping", "ranking"}:
        return AdminStopRunResponse(stopped=False, status=run.status, message=f"Run is already {run.status}")
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return AdminStopRunResponse(stopped=True, status="cancelled")


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


# ── Worker health ──────────────────────────────────────────────────────────


class WorkerRunSummary(BaseModel):
    run_id: str
    user_id: str
    status: str
    mode: str
    claimed_by: str | None
    lease_expires_at: str | None
    last_heartbeat_at: str | None
    trigger_source: str | None
    executor_type: str | None
    started_at: str | None


class WorkerHealthResponse(BaseModel):
    active_runs: list[WorkerRunSummary]


@router.get("/worker/health", response_model=WorkerHealthResponse)
async def worker_health(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all runs currently in a non-terminal state (pending/claimed/scraping/ranking)."""
    result = await db.execute(
        select(Run)
        .where(Run.status.in_(["pending", "claimed", "scraping", "ranking"]))
        .order_by(Run.started_at.desc())
        .limit(100)
    )
    runs = result.scalars().all()
    return WorkerHealthResponse(
        active_runs=[
            WorkerRunSummary(
                run_id=r.id,
                user_id=r.user_id,
                status=r.status,
                mode=r.mode,
                claimed_by=r.claimed_by,
                lease_expires_at=str(r.lease_expires_at) if r.lease_expires_at else None,
                last_heartbeat_at=str(r.last_heartbeat_at) if r.last_heartbeat_at else None,
                trigger_source=r.trigger_source,
                executor_type=r.executor_type,
                started_at=str(r.started_at) if r.started_at else None,
            )
            for r in runs
        ]
    )


@router.post("/runs/{run_id}/retry", status_code=200)
async def retry_run(
    run_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a failed/cancelled/timed_out run back to pending so the worker picks it up again."""
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("pending", "claimed", "scraping", "ranking"):
        raise HTTPException(status_code=409, detail=f"Run is currently active (status={run.status}). Stop it first.")
    run.status = "pending"
    run.error = None
    run.claim_token = None
    run.claimed_by = None
    run.lease_expires_at = None
    run.last_heartbeat_at = None
    run.finished_at = None
    run.trigger_source = "retry"
    await db.commit()
    await db.refresh(run)
    return {"run_id": run.id, "status": run.status}


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
