"""V4 DB scorer — async entry point replacing batch/ranker.py:score_jobs_for_user().

Produces output compatible with the job_results table schema so no migration is needed.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ranking.v4.embeddings import ann_prefilter_job_urls, attach_embeddings_to_jobs, get_resume_embedding
from ranking.v4.extraction import extract_profile_v4
from ranking.v4.scorer import load_weights, score_jobs

logger = logging.getLogger(__name__)

_JOB_WINDOW_DAYS = 15
_RANK_MAX_CANDIDATES = 2000
_RANK_DESCRIPTION_CHARS = 1200


async def _load_jobs(
    db: AsyncSession,
    job_urls: list[str] | None,
    role_clusters: set[str] | None,
) -> list[dict]:
    """Load jobs from DB as plain dicts (no pandas until final output)."""
    from api.models import JobRaw

    cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    cols = (
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, _RANK_DESCRIPTION_CHARS).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted,
        JobRaw.role_clusters, JobRaw.job_profile, JobRaw.embedding,
    )
    col_names = ["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted", "role_clusters", "job_profile", "embedding"]

    if job_urls:
        stmt = (
            select(*cols)
            .where(JobRaw.ingested_at >= cutoff)
            .where(JobRaw.job_url.in_(job_urls))
            .order_by(JobRaw.ingested_at.desc())
            .limit(_RANK_MAX_CANDIDATES)
        )
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

    # Optional cluster filter
    if role_clusters and "general" not in role_clusters:
        from domain.role_clusters import infer_clusters_from_job_text
        jobs = [
            j for j in jobs
            if infer_clusters_from_job_text(j.get("title"), j.get("description")).intersection(role_clusters)
        ]

    return jobs


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
            "final_score": raw_score * 100,
            "semantic_score": sem,
            "skills_score": features.get("skill_overlap", 0.0) * 100,
            "company_score": features.get("company_tier_score", 0.0) * 100,
            "seniority_score": ((sen + 1) / 2) * 100,  # [-1,1] → [0,100]
            "location_score": features.get("location_match", 0.0) * 100,
            "recency_score": features.get("recency_score", 0.0) * 100,
            "title_relevance_score": features.get("title_similarity", 0.0) * 100,
            # V4 doesn't have LLM agentic matching output (set to None)
            "fit_band": None,
            "confidence_band": None,
            "explanation_summary": None,
            "match_report": None,
            "verification_report": None,
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
) -> pd.DataFrame:
    """V4 async scorer. Drop-in replacement for batch/ranker.py:score_jobs_for_user().

    Returns a DataFrame with the same columns as V2 for job_results compatibility.
    """
    from domain.role_clusters import roles_to_clusters

    logger.info("V4 scorer: user=%s, job_urls=%s", user_id, len(job_urls) if job_urls else "all")

    # Build candidate profile from resume text
    profile = extract_profile_v4(
        resume_text,
        current_focus=(config_overrides or {}).get("current_focus"),
        config_overrides=config_overrides,
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
    jobs = await _load_jobs(db, effective_urls, clusters)
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
    scored = score_jobs(jobs, profile)

    # Convert to DataFrame for job_results insertion (keeps V2 interface)
    df = _results_to_dataframe(scored)
    logger.info("V4: scored %d jobs, top final_score=%.1f", len(df), df["final_score"].max() if not df.empty else 0)
    return df
