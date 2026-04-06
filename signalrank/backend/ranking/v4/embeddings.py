"""Embedding utilities for V4 scorer.

Extracted from batch/ranker.py to decouple embedding logic from the scoring pipeline.
Provides two public functions:
  - get_resume_embedding(db, user_id) -> list[float] | None
  - get_job_embeddings(db, job_ids) -> dict[str, list[float]]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

_JOB_WINDOW_DAYS = 15
_ANN_PREFILTER_CANDIDATES = 600


async def get_resume_embedding(db: AsyncSession, user_id: str) -> list[float] | None:
    """Fetch the stored resume embedding for a user from the Profile table."""
    from api.models import Profile
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile and profile.resume_embedding is not None:
        return list(profile.resume_embedding)
    return None


async def get_job_embeddings(
    db: AsyncSession,
    job_ids: list[str],
) -> dict[str, list[float]]:
    """Fetch stored embeddings for a list of job IDs.

    Returns only jobs that have a stored embedding. Jobs without embeddings
    are excluded — callers should treat missing keys as 0.0 similarity.
    """
    if not job_ids:
        return {}
    from api.models import JobRaw
    rows = await db.execute(
        select(JobRaw.id, JobRaw.embedding).where(
            JobRaw.id.in_(job_ids),
            JobRaw.embedding.is_not(None),
        )
    )
    return {str(row.id): list(row.embedding) for row in rows.all()}


async def ann_prefilter_job_urls(
    db: AsyncSession,
    resume_embedding: list[float],
    *,
    limit: int = _ANN_PREFILTER_CANDIDATES,
    cutoff: datetime | None = None,
) -> list[str]:
    """Return top-N job URLs by ANN similarity to the resume embedding.

    Uses the pgvector HNSW index on jobs_raw.embedding for fast candidate
    selection. Falls back to global pool if result count < 50 (caller handles).
    """
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    rows = await db.execute(
        text("""
            SELECT job_url FROM jobs_raw
            WHERE embedding IS NOT NULL
              AND ingested_at >= :cutoff
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """),
        {"vec": str(resume_embedding), "cutoff": cutoff, "limit": limit},
    )
    return [r[0] for r in rows.all()]


def attach_embeddings_to_jobs(
    jobs: list[dict],
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Attach stored embeddings to job dicts in-place (by job 'id' key)."""
    for job in jobs:
        job_id = str(job.get("id", ""))
        if job_id in embeddings:
            job["embedding"] = embeddings[job_id]
    return jobs
