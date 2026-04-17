from datetime import datetime, timedelta, timezone
from typing import Literal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Application, ArchivalQueue, JobFeedbackEvent, JobPreferenceMemory, JobRaw, JobResult, Profile, Run, User
from api.stats_cache import get_cached_stats, invalidate_stats_cache, set_cached_stats
from api.timezone import format_datetime_local
from api.routes.admin import require_admin
from domain.job_source import compute_freshness_bucket, is_direct_source
from domain.job_preferences import (
    QUICK_ACTIONS,
    PreferenceContext,
    build_feedback_delta,
    bucket_for_score,
    canonicalize_state,
    effective_preference_context,
    enrich_feedback_delta_with_llm,
    has_explicit_preferences,
    merge_preference_state,
    rerank_rows,
)
from scripts.profile_fresh_company_rank import generate_profile_fresh_company_rank

ARCHIVAL_TIERS = {"tier_ss", "tier_s", "tier_a"}
DEFAULT_JOBS_CACHE_PARAMS = {
    "page": 1,
    "limit": 10,
    "sort": "final_score",
    "sort_dir": "desc",
    "search": "",
    "show_archived": True,
    "min_score": 0,
    "tiers": [],
    "job_type": "all",
    "sites": [],
    "date_range": "any",
}

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_LEGACY_TIER_MAP = {
    "ss": "tier_ss",
    "s": "tier_s",
    "a": "tier_a",
    "b": "tier_b",
    "c": "tier_c",
    "d": "tier_d",
    "tier_ss": "tier_ss",
    "tier_s": "tier_s",
    "tier_a": "tier_a",
    "tier_b": "tier_b",
    "tier_c": "tier_c",
    "tier_d": "tier_d",
    "default": "default",
    "": "",
}


class JobsFeedbackRequest(BaseModel):
    run_id: str | None = None
    feedback_text: str | None = None
    quick_actions: list[str] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    session_intent: str | None = None
    page: int = 1
    limit: int = 50
    sort: Literal["final_score", "semantic_score", "skills_score", "company_score", "seniority_score", "location_score", "recency_score", "title_relevance_score", "date_posted"] = "final_score"
    sort_dir: Literal["asc", "desc"] = "desc"
    search: str = ""
    show_archived: bool = True
    min_score: int = 0
    tiers: list[str] = Field(default_factory=list)
    job_type: Literal["all", "fte", "contract"] = "all"
    sites: list[str] = Field(default_factory=list)
    date_range: Literal["any", "24h", "week", "month"] = "any"


class JobsPreferencesResetRequest(BaseModel):
    clear_all: bool = False
    categories: list[str] = Field(default_factory=list)


class ProfileFreshRequest(BaseModel):
    limit: int = 30
    country: str = "India"
    queries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)


class ProfileFreshResponse(BaseModel):
    output_csv: str
    summary_json: str
    scraped_jobs: int
    jobs_scored: int
    companies_exported: int
    rejection_counts: dict[str, int]
    rows: list[dict]


async def warm_default_jobs_cache(db: AsyncSession, *, user_id: str, tz_name: str | None = None) -> None:
    latest_run = await db.execute(
        select(Run)
        .where(Run.user_id == user_id, Run.status == "success")
        .order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc())
        .limit(1)
    )
    run = latest_run.scalar_one_or_none()
    if not run:
        return

    cache_key = _jobs_cache_key(user_id=user_id, run_id=run.id, tz_name=tz_name, **DEFAULT_JOBS_CACHE_PARAMS)
    if get_cached_stats(cache_key) is not None:
        return

    payload = await _build_jobs_payload(
        request=type("Request", (), {"headers": {"X-User-Timezone": tz_name}})(),
        run=run,
        page=DEFAULT_JOBS_CACHE_PARAMS["page"],
        limit=DEFAULT_JOBS_CACHE_PARAMS["limit"],
        sort=DEFAULT_JOBS_CACHE_PARAMS["sort"],
        sort_dir=DEFAULT_JOBS_CACHE_PARAMS["sort_dir"],
        search=DEFAULT_JOBS_CACHE_PARAMS["search"],
        show_archived=DEFAULT_JOBS_CACHE_PARAMS["show_archived"],
        min_score=DEFAULT_JOBS_CACHE_PARAMS["min_score"],
        tiers=DEFAULT_JOBS_CACHE_PARAMS["tiers"],
        job_type=DEFAULT_JOBS_CACHE_PARAMS["job_type"],
        sites=DEFAULT_JOBS_CACHE_PARAMS["sites"],
        date_range=DEFAULT_JOBS_CACHE_PARAMS["date_range"],
        current_user=type("User", (), {"id": user_id})(),
        db=db,
    )
    set_cached_stats(cache_key, payload)
    await _persist_default_jobs_cache(db, user_id=user_id, run_id=run.id, tz_name=tz_name, payload=payload)


def _jobs_cache_key(
    *,
    user_id: str,
    run_id: str,
    page: int,
    limit: int,
    sort: str,
    sort_dir: str,
    search: str,
    show_archived: bool,
    min_score: int,
    tiers: list[str],
    job_type: str,
    sites: list[str],
    date_range: str,
    tz_name: str | None,
) -> str:
    return "::".join(
        [
            "jobs_list",
            str(user_id),
            str(run_id),
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


async def _persist_default_jobs_cache(db: AsyncSession, *, user_id: str, run_id: str, tz_name: str | None, payload: dict) -> None:
    result = await db.execute(select(Run).where(Run.id == run_id, Run.user_id == user_id))
    run = result.scalar_one_or_none()
    if not run:
        return
    progress = dict(run.progress or {})
    progress["jobs_cache"] = {"default": payload, "tz": tz_name or "utc"}
    progress["jobs_summary"] = {
        "total": int(payload.get("total") or 0),
        "new_good_matches": int(payload.get("new_good_matches") or 0),
        "available_sites": list(payload.get("available_sites") or []),
    }
    run.progress = progress
    await db.commit()


async def _load_default_jobs_cache(db: AsyncSession, *, user_id: str, run_id: str, tz_name: str | None) -> dict | None:
    result = await db.execute(
        select(Run.progress).where(Run.id == run_id, Run.user_id == user_id)
    )
    progress = result.scalar_one_or_none()
    if not isinstance(progress, dict):
        return None
    cache = progress.get("jobs_cache")
    if not isinstance(cache, dict):
        return None
    if cache.get("tz") not in {tz_name or "utc", None}:
        return None
    default = cache.get("default")
    return default if isinstance(default, dict) else None


@router.post("/profile-fresh", response_model=ProfileFreshResponse)
async def run_profile_fresh_preview(
    body: ProfileFreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = (
        await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    ).scalar_one_or_none()
    if not profile or not profile.resume_text:
        raise HTTPException(status_code=400, detail="Resume text is required to run profile-fresh preview")

    output_dir = Path(__file__).resolve().parents[2] / "tmp" / "top100_company_rank_300"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_csv = output_dir / f"profile_fresh_{current_user.id}_{timestamp}.csv"

    result = await generate_profile_fresh_company_rank(
        resume_path=None,
        resume_text=profile.resume_text,
        output_csv=output_csv,
        limit=max(1, min(body.limit, 100)),
        country=body.country,
        terms=list(body.queries),
        locations=list(body.locations),
        sources=list(body.sources),
        companies=list(body.companies),
    )
    return ProfileFreshResponse(**result)


def _extract_cached_run_summary(run: Run) -> dict:
    progress = run.progress if isinstance(run.progress, dict) else {}
    summary = progress.get("jobs_summary")
    return summary if isinstance(summary, dict) else {}


def _canonical_company_tier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return _LEGACY_TIER_MAP.get(normalized, normalized or None)


def _rank_debug_payload(result: JobResult, job: JobRaw) -> dict:
    match_report = result.match_report if isinstance(result.match_report, dict) else {}
    why_up = [str(item).strip() for item in (match_report.get("why_rank_up") or []) if str(item).strip()]
    why_down = [str(item).strip() for item in (match_report.get("why_rank_down") or []) if str(item).strip()]

    if not why_up:
        if (result.title_relevance_score or 0) >= 80:
            why_up.append("Strong title match")
        if (result.skills_score or 0) >= 70:
            why_up.append("Strong skill overlap")
        if is_direct_source(job.site):
            why_up.append("Direct ATS source")
        if compute_freshness_bucket(job.date_posted, job.ingested_at, job.site) == "fresh":
            why_up.append("Fresh posting")

    if not why_down:
        if (result.title_relevance_score or 0) < 35:
            why_down.append("Weak title-role match")
        if (result.recency_score or 0) < 35:
            why_down.append("Freshness risk")
        if result.is_contract:
            why_down.append("Contract role")

    return {
        "rank_reason_up": why_up[0] if why_up else None,
        "rank_reason_down": why_down[0] if why_down else None,
        "rank_stage": "structured" if result.fit_band else "deterministic",
        "freshness_bucket": compute_freshness_bucket(job.date_posted, job.ingested_at, job.site),
        "is_direct_source": is_direct_source(job.site),
    }


def _serialize_job_payload(*, result: JobResult, job: JobRaw, tz_name: str | None, run: Run, preference_data: dict | None = None) -> dict:
    preference_data = preference_data or {}
    base_score = float(result.final_score or 0.0)
    preference_score = float(preference_data.get("preference_score", base_score))
    bucket_key, bucket_label = bucket_for_score(preference_score)
    return {
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
        "company_tier": (
            canonical_tier
            if (canonical_tier := _canonical_company_tier(result.company_tier)) not in ("default", "", None)
            else None
        ),
        "is_contract": result.is_contract,
        "archived_by_llm": result.archived_by_llm,
        "archival_reason": result.archival_reason,
        "preference_score": round(preference_score / 100, 4),
        "preference_bucket_key": str(preference_data.get("preference_bucket_key") or bucket_key),
        "preference_bucket": str(preference_data.get("preference_bucket") or bucket_label),
        "preference_tags": list(preference_data.get("preference_tags") or []),
        **_rank_debug_payload(result, job),
    }


async def _get_latest_success_run(
    db: AsyncSession,
    *,
    user_id: str,
    require_tiers: bool = False,
) -> Run | None:
    base_query = select(Run).where(Run.user_id == user_id, Run.status == "success")
    if require_tiers:
        tiered_query = (
            base_query.where(
                select(JobResult.id)
                .where(
                    JobResult.run_id == Run.id,
                    JobResult.user_id == user_id,
                    JobResult.company_tier.is_not(None),
                    JobResult.company_tier.notin_(["", "default"]),
                )
                .exists()
            )
            .order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc())
            .limit(1)
        )
        tiered_run = await db.execute(tiered_query)
        if (run := tiered_run.scalar_one_or_none()) is not None:
            return run

    meaningful_query = (
        base_query.where(Run.job_count >= 50)
        .order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc())
        .limit(1)
    )
    meaningful_run = await db.execute(meaningful_query)
    if (run := meaningful_run.scalar_one_or_none()) is not None:
        return run

    latest_run = await db.execute(
        base_query.order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc()).limit(1)
    )
    return latest_run.scalar_one_or_none()


async def _get_runs_with_tier_data(
    db: AsyncSession,
    *,
    user_id: str,
) -> list[Run]:
    """Return successful runs that have at least one job with non-null tier for the user."""
    query = (
        select(Run)
        .where(Run.user_id == user_id, Run.status == "success")
        .where(
            select(JobResult.id)
            .where(
                JobResult.run_id == Run.id,
                JobResult.user_id == user_id,
                JobResult.company_tier.is_not(None),
                JobResult.company_tier.notin_(["", "default"]),
            )
            .exists()
        )
        .order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc())
    )
    result = await db.execute(query)
    return result.scalars().all()


async def _get_success_runs(
    db: AsyncSession,
    *,
    user_id: str,
) -> list[Run]:
    result = await db.execute(
        select(Run)
        .where(Run.user_id == user_id, Run.status == "success")
        .order_by(Run.finished_at.desc().nulls_last(), Run.started_at.desc())
        .limit(50)
    )
    return result.scalars().all()


async def _get_requested_or_latest_success_run(
    db: AsyncSession,
    *,
    user_id: str,
    run_id: str | None,
    require_tiers: bool = False,
) -> Run | None:
    if run_id:
        requested = await db.execute(
            select(Run).where(Run.id == run_id, Run.user_id == user_id, Run.status == "success")
        )
        return requested.scalar_one_or_none()
    return await _get_latest_success_run(db, user_id=user_id, require_tiers=require_tiers)


async def _get_preference_context(db: AsyncSession, *, user_id: str) -> tuple[PreferenceContext, JobPreferenceMemory | None]:
    profile_row = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = profile_row.scalar_one_or_none()
    memory_row = await db.execute(select(JobPreferenceMemory).where(JobPreferenceMemory.user_id == user_id))
    memory = memory_row.scalar_one_or_none()
    context = effective_preference_context(profile=profile, stored_state=(memory.state_json if memory else None))
    return context, memory


async def _recent_feedback(db: AsyncSession, *, user_id: str, limit: int = 8) -> list[dict]:
    rows = await db.execute(
        select(JobFeedbackEvent)
        .where(JobFeedbackEvent.user_id == user_id)
        .order_by(JobFeedbackEvent.created_at.desc())
        .limit(limit)
    )
    events = []
    for event in rows.scalars().all():
        events.append(
            {
                "id": event.id,
                "feedback_text": event.feedback_text,
                "quick_actions": list(event.quick_actions or []),
                "job_ids": list(event.job_ids or []),
                "job_snapshots": list(event.job_snapshots or []),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        )
    return events


def _preferences_payload(context: PreferenceContext, memory: JobPreferenceMemory | None, recent_feedback: list[dict]) -> dict:
    return {
        "state": context.state,
        "summary_chips": context.summary_chips,
        "has_learned_preferences": context.has_learned_preferences,
        "updated_at": memory.updated_at.isoformat() if memory and memory.updated_at else None,
        "recent_feedback": recent_feedback,
    }


async def _build_jobs_payload_multi_run(
    *,
    request: Request,
    runs: list[Run],
    page: int,
    limit: int,
    sort: str,
    sort_dir: str,
    search: str,
    show_archived: bool,
    min_score: int,
    tiers: list[str],
    job_type: str,
    sites: list[str],
    date_range: str,
    current_user: User,
    db: AsyncSession,
    preference_context: PreferenceContext | None = None,
) -> dict:
    """Build jobs payload for multiple runs (used when tier filters are active)."""
    tz_name = request.headers.get("X-User-Timezone")
    sort_col = JobRaw.date_posted if sort == "date_posted" else getattr(JobResult, sort)
    order_expr = sort_col.asc().nulls_last() if sort_dir == "asc" else sort_col.desc().nulls_last()
    preference_context = preference_context or PreferenceContext(state=canonicalize_state(None), summary_chips=[], has_learned_preferences=False)
    preference_active = has_explicit_preferences(preference_context.state)

    # Get run IDs for filtering
    run_ids = [run.id for run in runs]
    run_total = sum(run.job_count or 0 for run in runs)

    base_filters = [JobResult.user_id == current_user.id, JobResult.run_id.in_(run_ids)]

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
        normalized_tiers = [_canonical_company_tier(tier) for tier in tiers if tier and tier != "unknown"]
        normalized_tiers = [tier for tier in normalized_tiers if tier and tier not in {"default", ""}]
        wants_unknown = "unknown" in tiers
        tier_clauses = []
        if normalized_tiers:
            legacy_values: set[str] = set(normalized_tiers)
            reverse_legacy = {
                "tier_ss": "SS",
                "tier_s": "S",
                "tier_a": "A",
                "tier_b": "B",
                "tier_c": "C",
                "tier_d": "D",
            }
            for tier in normalized_tiers:
                legacy = reverse_legacy.get(tier)
                if legacy:
                    legacy_values.add(legacy)
            tier_clauses.append(JobResult.company_tier.in_(sorted(legacy_values)))
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

    # Count total
    count_query = select(func.count()).select_from(JobResult).join(JobRaw, JobResult.job_id == JobRaw.id).where(*site_filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Count new good matches (for the most recent run only, to keep it meaningful)
    most_recent_run = runs[0] if runs else None
    new_good_matches = 0
    if most_recent_run:
        new_good_matches_result = await db.execute(
            select(func.count())
            .select_from(JobResult)
            .join(JobRaw, JobResult.job_id == JobRaw.id)
            .where(
                JobResult.run_id == most_recent_run.id,
                JobResult.user_id == current_user.id,
                JobResult.final_score >= 70,
                JobRaw.ingested_at >= most_recent_run.started_at,
                ~select(Application.job_id).where(
                    Application.user_id == current_user.id,
                    Application.job_id == JobResult.job_id,
                    Application.job_id.isnot(None),
                ).exists(),
            )
        )
        new_good_matches = new_good_matches_result.scalar() or 0

    # Get available sites
    sites_query = await db.execute(
        select(JobRaw.site)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(*base_filters, JobRaw.site.is_not(None))
        .distinct()
        .order_by(JobRaw.site.asc())
    )
    available_sites = [site for site in sites_query.scalars().all() if site]

    # Main query
    row_query = (
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(*site_filters)
        .order_by(order_expr)
    )
    if preference_active:
        candidate_limit = min(max(page * limit * 4, 200), 500)
        rows = (await db.execute(row_query.limit(candidate_limit))).all()
    else:
        rows = (
            await db.execute(
                row_query.offset((page - 1) * limit).limit(limit)
            )
        ).all()

    jobs = []
    if preference_active:
        reranked = rerank_rows(rows, state=preference_context.state, sort=sort, sort_dir=sort_dir)
        start = max(0, (page - 1) * limit)
        end = start + limit
        selected = reranked[start:end]
        for item in selected:
            # For multi-run, we need to get the run object for serialization
            run_for_item = next((r for r in runs if r.id == item["result"].run_id), runs[0] if runs else None)
            if run_for_item:
                jobs.append(
                    _serialize_job_payload(
                        result=item["result"],
                        job=item["job"],
                        tz_name=tz_name,
                        run=run_for_item,
                        preference_data=item,
                    )
                )
    else:
        for result, job in rows:
            # Find the run for this result
            run_for_item = next((r for r in runs if r.id == result.run_id), runs[0] if runs else None)
            if run_for_item:
                jobs.append(_serialize_job_payload(result=result, job=job, tz_name=tz_name, run=run_for_item))

    return {
        "jobs": jobs,
        "total": total,
        "run_total": run_total,
        "available_sites": available_sites,
        "page": page,
        "limit": limit,
        "new_good_matches": new_good_matches,
    }


async def _build_jobs_payload(
    *,
    request: Request,
    run: Run,
    page: int,
    limit: int,
    sort: str,
    sort_dir: str,
    search: str,
    show_archived: bool,
    min_score: int,
    tiers: list[str],
    job_type: str,
    sites: list[str],
    date_range: str,
    current_user: User,
    db: AsyncSession,
    preference_context: PreferenceContext | None = None,
) -> dict:
    tz_name = request.headers.get("X-User-Timezone")
    sort_col = JobRaw.date_posted if sort == "date_posted" else getattr(JobResult, sort)
    order_expr = sort_col.asc().nulls_last() if sort_dir == "asc" else sort_col.desc().nulls_last()
    preference_context = preference_context or PreferenceContext(state=canonicalize_state(None), summary_chips=[], has_learned_preferences=False)
    preference_active = has_explicit_preferences(preference_context.state)

    base_filters = [JobResult.user_id == current_user.id, JobResult.run_id == run.id]
    run_total = run.job_count or 0
    cached_summary = _extract_cached_run_summary(run)

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
        normalized_tiers = [_canonical_company_tier(tier) for tier in tiers if tier and tier != "unknown"]
        normalized_tiers = [tier for tier in normalized_tiers if tier and tier not in {"default", ""}]
        wants_unknown = "unknown" in tiers
        tier_clauses = []
        if normalized_tiers:
            legacy_values: set[str] = set(normalized_tiers)
            reverse_legacy = {
                "tier_ss": "SS",
                "tier_s": "S",
                "tier_a": "A",
                "tier_b": "B",
                "tier_c": "C",
                "tier_d": "D",
            }
            for tier in normalized_tiers:
                legacy = reverse_legacy.get(tier)
                if legacy:
                    legacy_values.add(legacy)
            tier_clauses.append(JobResult.company_tier.in_(sorted(legacy_values)))
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

    is_default_filters = (
        page == DEFAULT_JOBS_CACHE_PARAMS["page"]
        and limit == DEFAULT_JOBS_CACHE_PARAMS["limit"]
        and sort == DEFAULT_JOBS_CACHE_PARAMS["sort"]
        and sort_dir == DEFAULT_JOBS_CACHE_PARAMS["sort_dir"]
        and search == DEFAULT_JOBS_CACHE_PARAMS["search"]
        and show_archived == DEFAULT_JOBS_CACHE_PARAMS["show_archived"]
        and min_score == DEFAULT_JOBS_CACHE_PARAMS["min_score"]
        and tiers == DEFAULT_JOBS_CACHE_PARAMS["tiers"]
        and job_type == DEFAULT_JOBS_CACHE_PARAMS["job_type"]
        and sites == DEFAULT_JOBS_CACHE_PARAMS["sites"]
        and date_range == DEFAULT_JOBS_CACHE_PARAMS["date_range"]
    )

    if is_default_filters:
        total = int(cached_summary.get("total") or run_total)
        new_good_matches = int(cached_summary.get("new_good_matches") or 0)
        available_sites = cached_summary.get("available_sites")
        if not isinstance(available_sites, list):
            available_sites = []
    else:
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
                ~select(Application.job_id).where(
                    Application.user_id == current_user.id,
                    Application.job_id == JobResult.job_id,
                    Application.job_id.isnot(None),
                ).exists(),
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

    row_query = (
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(*site_filters)
        .order_by(order_expr)
    )
    if preference_active:
        candidate_limit = min(max(page * limit * 4, 200), 500)
        rows = (await db.execute(row_query.limit(candidate_limit))).all()
    else:
        rows = (
            await db.execute(
                row_query.offset((page - 1) * limit).limit(limit)
            )
        ).all()

    jobs = []
    if preference_active:
        reranked = rerank_rows(rows, state=preference_context.state, sort=sort, sort_dir=sort_dir)
        start = max(0, (page - 1) * limit)
        end = start + limit
        selected = reranked[start:end]
        for item in selected:
            jobs.append(
                _serialize_job_payload(
                    result=item["result"],
                    job=item["job"],
                    tz_name=tz_name,
                    run=run,
                    preference_data=item,
                )
            )
    else:
        for result, job in rows:
            jobs.append(_serialize_job_payload(result=result, job=job, tz_name=tz_name, run=run))

    return {
        "jobs": jobs,
        "total": total,
        "run_total": run_total,
        "available_sites": available_sites,
        "page": page,
        "limit": limit,
        "new_good_matches": new_good_matches,
    }


@router.get("")
async def list_jobs(
    request: Request,
    run_id: str | None = Query(None),
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

    runs_to_use: list[Run] = []
    if run_id and run_id != "all":
        requested = await db.execute(
            select(Run).where(Run.id == run_id, Run.user_id == current_user.id, Run.status == "success")
        )
        run = requested.scalar_one_or_none()
        if run:
            runs_to_use = [run]
    else:
        if tiers:
            runs_to_use = await _get_runs_with_tier_data(db, user_id=current_user.id)
            if not runs_to_use:
                run = await _get_latest_success_run(db, user_id=current_user.id, require_tiers=False)
                if run:
                    runs_to_use = [run]
        else:
            runs_to_use = await _get_success_runs(db, user_id=current_user.id)

    if not runs_to_use:
        return {"jobs": [], "total": 0, "page": page, "limit": limit, "new_good_matches": 0}

    preference_context, memory = await _get_preference_context(db, user_id=current_user.id)
    use_cache = not has_explicit_preferences(preference_context.state)

    representative_run = runs_to_use[0] if runs_to_use else None
    cache_key = None
    if use_cache and representative_run:
        cache_key = _jobs_cache_key(
            user_id=current_user.id,
            run_id=representative_run.id,
            page=page,
            limit=limit,
            sort=sort,
            sort_dir=sort_dir,
            search=search,
            show_archived=show_archived,
            min_score=min_score,
            tiers=tiers,
            job_type=job_type,
            sites=sites,
            date_range=date_range,
            tz_name=tz_name,
        )
        cached = get_cached_stats(cache_key)
        if cached is not None:
            return cached
        if (
            page == DEFAULT_JOBS_CACHE_PARAMS["page"]
            and limit == DEFAULT_JOBS_CACHE_PARAMS["limit"]
            and sort == DEFAULT_JOBS_CACHE_PARAMS["sort"]
            and sort_dir == DEFAULT_JOBS_CACHE_PARAMS["sort_dir"]
            and search == DEFAULT_JOBS_CACHE_PARAMS["search"]
            and show_archived == DEFAULT_JOBS_CACHE_PARAMS["show_archived"]
            and min_score == DEFAULT_JOBS_CACHE_PARAMS["min_score"]
            and tiers == DEFAULT_JOBS_CACHE_PARAMS["tiers"]
            and job_type == DEFAULT_JOBS_CACHE_PARAMS["job_type"]
            and sites == DEFAULT_JOBS_CACHE_PARAMS["sites"]
            and date_range == DEFAULT_JOBS_CACHE_PARAMS["date_range"]
        ):
            persisted = await _load_default_jobs_cache(db, user_id=current_user.id, run_id=representative_run.id, tz_name=tz_name)
            if persisted is not None:
                set_cached_stats(cache_key, persisted)
                return persisted

    is_default_filters = (
        page == DEFAULT_JOBS_CACHE_PARAMS["page"]
        and limit == DEFAULT_JOBS_CACHE_PARAMS["limit"]
        and sort == DEFAULT_JOBS_CACHE_PARAMS["sort"]
        and sort_dir == DEFAULT_JOBS_CACHE_PARAMS["sort_dir"]
        and search == DEFAULT_JOBS_CACHE_PARAMS["search"]
        and show_archived == DEFAULT_JOBS_CACHE_PARAMS["show_archived"]
        and min_score == DEFAULT_JOBS_CACHE_PARAMS["min_score"]
        and tiers == DEFAULT_JOBS_CACHE_PARAMS["tiers"]
        and job_type == DEFAULT_JOBS_CACHE_PARAMS["job_type"]
        and sites == DEFAULT_JOBS_CACHE_PARAMS["sites"]
        and date_range == DEFAULT_JOBS_CACHE_PARAMS["date_range"]
    )

    payload = await _build_jobs_payload_multi_run(
        request=request,
        runs=runs_to_use,
        page=page,
        limit=limit,
        sort=sort,
        sort_dir=sort_dir,
        search=search,
        show_archived=show_archived,
        min_score=min_score,
        tiers=tiers,
        job_type=job_type,
        sites=sites,
        date_range=date_range,
        current_user=current_user,
        db=db,
        preference_context=preference_context,
    )
    if cache_key is not None:
        set_cached_stats(cache_key, payload)
    if is_default_filters and use_cache and representative_run:
        await _persist_default_jobs_cache(db, user_id=current_user.id, run_id=representative_run.id, tz_name=tz_name, payload=payload)
    return payload


@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context, memory = await _get_preference_context(db, user_id=current_user.id)
    recent_feedback = await _recent_feedback(db, user_id=current_user.id)
    return _preferences_payload(context, memory, recent_feedback)


@router.post("/preferences/reset")
async def reset_preferences(
    body: JobsPreferencesResetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context, memory = await _get_preference_context(db, user_id=current_user.id)
    if memory is None:
        return _preferences_payload(context, memory, [])

    if body.clear_all or not body.categories:
        memory.state_json = {}
        memory.summary_json = {}
    else:
        state = canonicalize_state(memory.state_json)
        for category in body.categories:
            if category in state:
                state[category] = [] if isinstance(state[category], list) else {}
        memory.state_json = state
        memory.summary_json = {"categories": body.categories}
    memory.last_feedback_at = datetime.now(timezone.utc)
    await db.commit()
    invalidate_stats_cache()
    refreshed_context, refreshed_memory = await _get_preference_context(db, user_id=current_user.id)
    recent_feedback = await _recent_feedback(db, user_id=current_user.id)
    return _preferences_payload(refreshed_context, refreshed_memory, recent_feedback)


@router.post("/feedback")
async def post_feedback(
    body: JobsFeedbackRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    invalid_actions = sorted(set(body.quick_actions) - QUICK_ACTIONS)
    if invalid_actions:
        raise HTTPException(status_code=422, detail=f"invalid quick_actions: {', '.join(invalid_actions)}")
    feedback_text = str(body.feedback_text or "").strip()
    if not feedback_text and not body.quick_actions:
        raise HTTPException(status_code=422, detail="feedback_text or quick_actions required")

    requested_all_runs = body.run_id == "all"
    run = None if requested_all_runs else await _get_requested_or_latest_success_run(
        db,
        user_id=current_user.id,
        run_id=body.run_id,
        require_tiers=bool(body.tiers),
    )
    _, memory = await _get_preference_context(db, user_id=current_user.id)
    target_jobs: list[JobRaw] = []
    job_snapshots: list[dict] = []
    if body.job_ids:
        rows = await db.execute(select(JobRaw).where(JobRaw.id.in_(body.job_ids)))
        target_jobs = rows.scalars().all()
        for job in target_jobs:
            job_snapshots.append(
                {
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "site": job.site,
                }
            )

    delta = build_feedback_delta(feedback_text=feedback_text, quick_actions=body.quick_actions, jobs=target_jobs)
    profile_row = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = profile_row.scalar_one_or_none()
    llm = get_llm_client()
    delta = await enrich_feedback_delta_with_llm(
        feedback_text=feedback_text,
        base_delta=delta,
        profile=profile,
        llm=llm,
        db=db,
    )

    learned_state = canonicalize_state(memory.state_json if memory else None)
    next_state = merge_preference_state(learned_state, delta)
    now = datetime.now(timezone.utc)
    if memory is None:
        memory = JobPreferenceMemory(
            user_id=current_user.id,
            state_json=next_state,
            summary_json={"summary_chips": effective_preference_context(profile=profile, stored_state=next_state).summary_chips},
            last_feedback_at=now,
        )
        db.add(memory)
    else:
        memory.state_json = next_state
        memory.summary_json = {"summary_chips": effective_preference_context(profile=profile, stored_state=next_state).summary_chips}
        memory.last_feedback_at = now

    db.add(
        JobFeedbackEvent(
            user_id=current_user.id,
            run_id=run.id if run else None,
            feedback_text=feedback_text,
            quick_actions=body.quick_actions,
            job_ids=body.job_ids,
            job_snapshots=job_snapshots,
            extracted_delta=delta,
            session_context={
                "session_intent": body.session_intent,
                "filters": {
                    "page": body.page,
                    "limit": body.limit,
                    "sort": body.sort,
                    "sort_dir": body.sort_dir,
                    "search": body.search,
                    "show_archived": body.show_archived,
                    "min_score": body.min_score,
                    "tiers": body.tiers,
                    "job_type": body.job_type,
                    "sites": body.sites,
                    "date_range": body.date_range,
                },
            },
        )
    )
    await db.commit()
    invalidate_stats_cache()

    refreshed_context, refreshed_memory = await _get_preference_context(db, user_id=current_user.id)
    recent_feedback = await _recent_feedback(db, user_id=current_user.id)
    if run is None and not requested_all_runs:
        return {
            "preferences": _preferences_payload(refreshed_context, refreshed_memory, recent_feedback),
            "jobs_payload": {"jobs": [], "total": 0, "page": body.page, "limit": body.limit, "new_good_matches": 0},
        }

    if requested_all_runs:
        if body.tiers:
            runs_to_use = await _get_runs_with_tier_data(db, user_id=current_user.id)
            if not runs_to_use:
                fallback_run = await _get_latest_success_run(db, user_id=current_user.id, require_tiers=False)
                runs_to_use = [fallback_run] if fallback_run else []
        else:
            runs_to_use = await _get_success_runs(db, user_id=current_user.id)
        jobs_payload = await _build_jobs_payload_multi_run(
            request=request,
            runs=runs_to_use,
            page=body.page,
            limit=body.limit,
            sort=body.sort,
            sort_dir=body.sort_dir,
            search=body.search,
            show_archived=body.show_archived,
            min_score=body.min_score,
            tiers=body.tiers,
            job_type=body.job_type,
            sites=body.sites,
            date_range=body.date_range,
            current_user=current_user,
            db=db,
            preference_context=refreshed_context,
        ) if runs_to_use else {"jobs": [], "total": 0, "page": body.page, "limit": body.limit, "new_good_matches": 0}
    else:
        jobs_payload = await _build_jobs_payload(
            request=request,
            run=run,
            page=body.page,
            limit=body.limit,
            sort=body.sort,
            sort_dir=body.sort_dir,
            search=body.search,
            show_archived=body.show_archived,
            min_score=body.min_score,
            tiers=body.tiers,
            job_type=body.job_type,
            sites=body.sites,
            date_range=body.date_range,
            current_user=current_user,
            db=db,
            preference_context=refreshed_context,
        )
    return {
        "preferences": _preferences_payload(refreshed_context, refreshed_memory, recent_feedback),
        "jobs_payload": jobs_payload,
    }


@router.post("/archive-unsuitable", status_code=200)
async def archive_unsuitable(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue all unevaluated SS/S/A tier JobResults for LLM archival evaluation."""
    run = await _get_latest_success_run(db, user_id=current_user.id)
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
    run = await _get_latest_success_run(db, user_id=current_user.id)
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
    preference_context, _ = await _get_preference_context(db, user_id=current_user.id)
    result = await db.execute(
        select(JobResult, JobRaw)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(JobRaw.id == job_id, JobResult.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job_result, job = row
    run = await _get_latest_success_run(db, user_id=current_user.id)
    preference_data = rerank_rows([(job_result, job)], state=preference_context.state, sort="final_score", sort_dir="desc")[0]
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
        "preference_score": round(float(preference_data["preference_score"]) / 100, 4),
        "preference_bucket_key": preference_data["preference_bucket_key"],
        "preference_bucket": preference_data["preference_bucket"],
        "preference_tags": preference_data["preference_tags"],
        **_rank_debug_payload(job_result, job),
    }
