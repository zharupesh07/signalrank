"""V4 DB scorer — async entry point replacing batch/ranker.py:score_jobs_for_user().

Produces output compatible with the job_results table schema so no migration is needed.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.job_source import compute_freshness_bucket, is_direct_source
from ranking.v4.embeddings import ann_prefilter_job_urls, attach_embeddings_to_jobs, get_resume_embedding
from ranking.v4.extraction import extract_profile_v4
from ranking.v4.scorer import load_weights, score_jobs

logger = logging.getLogger(__name__)

_JOB_WINDOW_DAYS = 15
_RANK_MAX_CANDIDATES = 2000
_RANK_DESCRIPTION_CHARS = 1200
_STRUCTURED_COMPARE_TOP_K = 25
_STRUCTURED_COMPARE_SCAN_K = 120
_STRUCTURED_COMPARE_DIRECT_FLOOR = 5
_CONTEXT_MATCH_SKILLS = {
    "python",
    "sql",
    "bash",
    "gcp",
    "aws",
    "azure",
    "docker",
    "oidc",
    "rbac",
    "jenkins",
    "github actions",
    "langfuse",
    "fastapi",
}


async def _load_jobs(
    db: AsyncSession,
    job_urls: list[str] | None,
    role_clusters: set[str] | None,
    *,
    preserve_corpus: bool = False,
) -> list[dict]:
    """Load jobs from DB as plain dicts (no pandas until final output)."""
    from api.models import JobRaw

    cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    cols = (
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, _RANK_DESCRIPTION_CHARS).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted,
        JobRaw.ingested_at, JobRaw.role_clusters, JobRaw.job_profile, JobRaw.embedding,
    )
    col_names = ["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted", "ingested_at", "role_clusters", "job_profile", "embedding"]

    source_rank = case(
        (JobRaw.site.in_(["greenhouse", "ashby", "lever"]), 3),
        (JobRaw.site.in_(["manual", "himalayas", "remotive", "jobicy"]), 2),
        else_=1,
    )

    if job_urls:
        stmt = (
            select(*cols)
            .where(JobRaw.job_url.in_(job_urls))
            .order_by(source_rank.desc(), JobRaw.date_posted.desc().nulls_last(), JobRaw.ingested_at.desc())
        )
        if not preserve_corpus:
            stmt = stmt.where(JobRaw.ingested_at >= cutoff).limit(_RANK_MAX_CANDIDATES)
    else:
        _co = func.lower(func.trim(JobRaw.company))
        _ti = func.lower(func.trim(JobRaw.title))
        _lo = func.lower(func.trim(JobRaw.location))
        stmt = (
            select(*cols)
            .distinct(_co, _ti, _lo)
            .where(JobRaw.ingested_at >= cutoff)
            .order_by(
                _co, _ti, _lo,
                source_rank.desc(),
                JobRaw.date_posted.desc().nulls_last(),
                func.length(JobRaw.description).desc().nulls_last(),
                JobRaw.ingested_at.desc(),
            )
            .limit(_RANK_MAX_CANDIDATES)
        )

    result = await db.execute(stmt)
    rows = result.all()
    jobs = [dict(zip(col_names, row)) for row in rows]

    # Convert id to string for consistent key usage
    for j in jobs:
        j["id"] = str(j["id"])
        if isinstance(j.get("date_posted"), datetime):
            j["date_posted"] = j["date_posted"].isoformat()
        if isinstance(j.get("ingested_at"), datetime):
            j["ingested_at"] = j["ingested_at"].isoformat()

    # Optional cluster filter
    if role_clusters and "general" not in role_clusters and not preserve_corpus:
        from domain.role_clusters import infer_clusters_from_job_text
        jobs = [
            j for j in jobs
            if infer_clusters_from_job_text(j.get("title"), j.get("description")).intersection(role_clusters)
        ]

    return jobs


def _candidate_profile_for_match(profile, resume_text: str) -> dict:
    weighted_skills = [ws.name for ws in getattr(profile, "weighted_skills", [])]
    must_have_terms = list(getattr(profile, "must_have_terms", []) or [])
    secondary_skills = [
        skill for skill in weighted_skills
        if skill not in must_have_terms and skill not in _CONTEXT_MATCH_SKILLS
    ][:16]
    context_skills = [
        skill for skill in weighted_skills
        if skill in _CONTEXT_MATCH_SKILLS
    ][:16]
    return {
        "target_roles_primary": list(getattr(profile, "target_roles", []) or [])[:6],
        "target_roles_adjacent": list(getattr(profile, "target_roles", []) or [])[1:7],
        "negative_roles": list(getattr(profile, "avoid_terms", []) or [])[:12],
        "preferred_locations": list(getattr(profile, "preferred_locations", []) or [])[:6],
        "preferred_work_modes": ["remote"] if "Remote" in (getattr(profile, "preferred_locations", []) or []) else ["onsite", "hybrid", "remote"],
        "core_skills": must_have_terms[:12],
        "secondary_skills": secondary_skills,
        "context_skills": context_skills,
        "must_have_skills": must_have_terms[:12],
        "good_to_have_skills": secondary_skills,
        "seniority_band": getattr(profile, "seniority_band", "mid"),
        "preferred_domains": list(getattr(profile, "domains", []) or []),
        "evidence_snippets": [{"source": "resume_text", "text": resume_text[:240]}] if resume_text else [],
    }


def _structured_compare_indices(ranked: list[dict]) -> set[int]:
    base = set(range(min(_STRUCTURED_COMPARE_TOP_K, len(ranked))))
    direct_candidates = [
        idx
        for idx, job in enumerate(ranked[:_STRUCTURED_COMPARE_SCAN_K])
        if is_direct_source(job.get("site"))
    ]
    direct_base_count = sum(1 for idx in base if idx in direct_candidates)
    needed = max(0, min(_STRUCTURED_COMPARE_DIRECT_FLOOR, len(direct_candidates)) - direct_base_count)
    for idx in direct_candidates:
        if idx in base:
            continue
        if needed <= 0:
            break
        base.add(idx)
        needed -= 1
    return base


def _direct_source_score_bonus(job: dict) -> float:
    if not is_direct_source(job.get("site")):
        return 0.0
    features = job.get("features") if isinstance(job.get("features"), dict) else {}
    if not features:
        return 0.0
    if features.get("negative_hits", 0.0) >= 0.2:
        return 0.0
    if features.get("role_shape_match", 0.0) < 0.45:
        return 0.0
    if features.get("seniority_match", 0.0) < 0:
        return 0.0
    title_similarity = float(features.get("title_similarity", 0.0) or 0.0)
    role_family_match = float(features.get("role_family_match", 0.0) or 0.0)
    must_have_hits = float(features.get("must_have_hits", 0.0) or 0.0)
    location_match = float(features.get("location_match", 0.0) or 0.0)
    recency = float(features.get("recency_score", 0.0) or 0.0)
    freshness = compute_freshness_bucket(job.get("date_posted"), job.get("ingested_at"), job.get("site"))

    bonus = 0.0
    if title_similarity >= 0.3:
        bonus += 3.0
    if role_family_match >= 0.35 or must_have_hits >= 0.15:
        bonus += 2.0
    if location_match >= 0.5:
        bonus += 1.0
    if recency >= 0.75 or freshness == "fresh":
        bonus += 2.0
    return bonus


def _apply_structured_comparison(scored: list[dict], profile, resume_text: str) -> list[dict]:
    from domain.match_judge import heuristic_match_report
    from domain.score_synthesis import synthesize_match_score

    candidate_profile = _candidate_profile_for_match(profile, resume_text)
    enriched: list[dict] = []
    ranked = sorted(scored, key=lambda item: item.get("score", 0.0), reverse=True)
    structured_indices = _structured_compare_indices(ranked)

    for idx, job in enumerate(ranked):
        deterministic_score = float(job.get("score", 0.0) or 0.0) * 100
        if idx not in structured_indices:
            enriched.append(
                {
                    **job,
                    "final_score": deterministic_score + _direct_source_score_bonus(job),
                    "fit_band": None,
                    "confidence_band": None,
                    "explanation_summary": None,
                    "match_report": None,
                    "verification_report": None,
                }
            )
            continue

        job_profile = job.get("job_profile") if isinstance(job.get("job_profile"), dict) else {}
        if not job_profile:
            enriched.append(
                {
                    **job,
                    "final_score": deterministic_score,
                    "fit_band": None,
                    "confidence_band": None,
                    "explanation_summary": None,
                    "match_report": None,
                    "verification_report": None,
                }
            )
            continue

        match_report = heuristic_match_report(
            candidate_profile=candidate_profile,
            job_profile=job_profile,
            resume_text=resume_text,
            job_text=str(job.get("description") or ""),
        )
        synthesized = synthesize_match_score(
            deterministic_score=deterministic_score,
            match_report=match_report,
            verification_report=None,
        )
        why_up = list(match_report.get("why_rank_up") or [])
        why_down = list(match_report.get("why_rank_down") or [])
        if is_direct_source(job.get("site")):
            why_up = ["Direct ATS source", *why_up]
        enriched.append(
            {
                **job,
                "final_score": synthesized["final_score"] + _direct_source_score_bonus(job),
                "fit_band": synthesized["fit_band"],
                "confidence_band": synthesized["confidence_band"],
                "explanation_summary": synthesized["explanation_summary"],
                "match_report": {
                    **match_report,
                    "why_rank_up": why_up[:3],
                    "why_rank_down": why_down[:3],
                },
                "verification_report": None,
                "rank_stage": "structured",
            }
        )

    return sorted(enriched, key=lambda item: item.get("final_score", 0.0), reverse=True)


def _results_to_dataframe(scored: list[dict]) -> pd.DataFrame:
    """Convert scored jobs list to DataFrame compatible with job_results table columns."""
    rows = []
    for j in scored:
        features = j.get("features", {})
        sem = features.get("semantic_similarity", 0.0)
        raw_score = j.get("score", 0.0)  # already normalized [0, 1]
        sen = features.get("seniority_match", 0.0)  # [-1, 1]

        rows.append({
            "job_url": j.get("job_url"),
            "id": j.get("id"),
            "title": j.get("title"),
            "company": j.get("company"),
            "location": j.get("location"),
            "site": j.get("site"),
            "date_posted": j.get("date_posted"),
            # Score columns mapped to [0-100] for job_results compatibility
            "final_score": j.get("final_score", raw_score * 100),
            "semantic_score": sem,
            "skills_score": features.get("skill_overlap", 0.0) * 100,
            "company_score": features.get("company_tier_score", 0.0) * 100,
            "seniority_score": ((sen + 1) / 2) * 100,  # [-1,1] → [0,100]
            "location_score": features.get("location_match", 0.0) * 100,
            "recency_score": features.get("recency_score", 0.0) * 100,
            "title_relevance_score": features.get("title_similarity", 0.0) * 100,
            "fit_band": j.get("fit_band"),
            "confidence_band": j.get("confidence_band"),
            "explanation_summary": j.get("explanation_summary"),
            "match_report": j.get("match_report"),
            "verification_report": j.get("verification_report"),
            "company_tier": (j.get("job_profile") or {}).get("company_tier"),
            "is_contract": (j.get("job_profile") or {}).get("is_contract"),
        })
    return pd.DataFrame(rows)


async def score_jobs_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
    job_urls: list[str] | None = None,
    preserve_corpus: bool = False,
) -> pd.DataFrame:
    """V4 async scorer. Drop-in replacement for batch/ranker.py:score_jobs_for_user().

    Returns a DataFrame with the same columns as V2 for job_results compatibility.
    """
    from domain.role_clusters import roles_to_clusters
    from api.models import Profile

    logger.info("V4 scorer: user=%s, job_urls=%s", user_id, len(job_urls) if job_urls else "all")

    profile_row = (
        await db.execute(select(Profile).where(Profile.user_id == user_id).limit(1))
    ).scalar_one_or_none()
    merged_overrides = dict(config_overrides or {})
    v4_profile = dict((merged_overrides.get("v4_profile") or {}))
    if profile_row is not None:
        if getattr(profile_row, "target_roles", None) and not v4_profile.get("target_roles"):
            v4_profile["target_roles"] = list(profile_row.target_roles)
        if getattr(profile_row, "preferred_locations", None) and not v4_profile.get("preferred_locations"):
            v4_profile["preferred_locations"] = list(profile_row.preferred_locations)
    if v4_profile:
        merged_overrides["v4_profile"] = v4_profile

    # Build candidate profile from resume text
    profile = extract_profile_v4(
        resume_text,
        current_focus=merged_overrides.get("current_focus"),
        config_overrides=merged_overrides,
    )

    # Get resume embedding for semantic_similarity feature
    resume_emb = await get_resume_embedding(db, user_id)
    profile.resume_embedding = resume_emb

    # ANN pre-filter: narrow candidates using embedding similarity
    effective_urls = job_urls
    if effective_urls is None and resume_emb is not None:
        ann_urls = await ann_prefilter_job_urls(db, resume_emb)
        if len(ann_urls) >= 50:
            effective_urls = ann_urls
            logger.info("V4: ANN pre-filter selected %d candidates", len(ann_urls))

    # Resolve role clusters for SQL-level pre-filtering
    clusters = roles_to_clusters(profile.target_roles) if profile.target_roles else None

    # Load jobs from DB
    jobs = await _load_jobs(db, effective_urls, clusters, preserve_corpus=preserve_corpus)
    logger.info("V4: loaded %d jobs for scoring", len(jobs))

    if not jobs:
        return pd.DataFrame()

    # Attach job embeddings to job dicts
    job_ids = [j["id"] for j in jobs if j.get("id")]
    if job_ids:
        from ranking.v4.embeddings import get_job_embeddings
        emb_map = await get_job_embeddings(db, job_ids)
        attach_embeddings_to_jobs(jobs, emb_map)
        logger.info("V4: attached embeddings for %d/%d jobs", len(emb_map), len(jobs))

    # Score all jobs (scores already normalized to [0,1] absolute by score_jobs)
    scored = score_jobs(jobs, profile, dedupe=not preserve_corpus)

    scored = _apply_structured_comparison(scored, profile, resume_text)

    # Convert to DataFrame for job_results insertion (keeps V2 interface)
    df = _results_to_dataframe(scored)
    logger.info("V4: scored %d jobs, top final_score=%.1f", len(df), df["final_score"].max() if not df.empty else 0)
    return df
