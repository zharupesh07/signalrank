"""Sync top-k job_results + their jobs_raw rows from local DB to Railway DB.

Called by local_worker.py after V4 ranking completes. Handles ID remapping:
local jobs_raw.id may differ from Railway jobs_raw.id for the same job_url.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, JobResult

logger = logging.getLogger(__name__)


async def sync_results_to_railway(
    local_db: AsyncSession,
    railway_db: AsyncSession,
    user_id: str,
    run_id: str,
    top_k: int = 100,
) -> int:
    """Upsert top-k job_results + their jobs_raw rows to railway_db.

    Returns number of job_results rows synced.
    Steps:
      1. Read top-k job_results + jobs_raw from local_db
      2. Upsert jobs_raw to railway_db (sans embedding) by job_url conflict
      3. Fetch Railway jobs_raw.id to remap FKs
      4. Upsert job_results to railway_db using Railway job IDs
    """
    # 1. Read top-k results from local DB
    result = await local_db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(JobResult.user_id == user_id, JobResult.run_id == run_id)
        .order_by(JobResult.final_score.desc())
        .limit(top_k)
    )
    rows = result.all()
    if not rows:
        logger.info("local_sync: no results found for run %s user %s", run_id, user_id)
        return 0

    # 2. Upsert jobs_raw to Railway (sans embedding column)
    jobs_data = [
        {
            "id": j.id,
            "job_url": j.job_url,
            "title": j.title,
            "company": j.company,
            "description": j.description,
            "location": j.location,
            "site": j.site,
            "date_posted": j.date_posted,
            "job_profile": j.job_profile,
            "role_clusters": j.role_clusters,
            "ingested_at": j.ingested_at or datetime.now(timezone.utc),
        }
        for _, j in rows
    ]
    await railway_db.execute(
        pg_insert(JobRaw)
        .values(jobs_data)
        .on_conflict_do_update(
            index_elements=["job_url"],
            set_={
                "title": pg_insert(JobRaw).excluded.title,
                "company": pg_insert(JobRaw).excluded.company,
                "description": pg_insert(JobRaw).excluded.description,
                "location": pg_insert(JobRaw).excluded.location,
                "site": pg_insert(JobRaw).excluded.site,
                "date_posted": pg_insert(JobRaw).excluded.date_posted,
                "job_profile": pg_insert(JobRaw).excluded.job_profile,
                "role_clusters": pg_insert(JobRaw).excluded.role_clusters,
            },
        )
    )

    # 3. Fetch Railway IDs by job_url (may differ from local IDs)
    job_urls = [j.job_url for _, j in rows]
    rw_rows = await railway_db.execute(
        select(JobRaw.id, JobRaw.job_url).where(JobRaw.job_url.in_(job_urls))
    )
    url_to_rw_id: dict[str, str] = {r.job_url: r.id for r in rw_rows.all()}

    # 4. Upsert job_results with remapped job IDs
    results_data = []
    for jr, j in rows:
        rw_job_id = url_to_rw_id.get(j.job_url)
        if not rw_job_id:
            logger.warning("local_sync: no Railway job_id found for url %s, skipping", j.job_url)
            continue
        results_data.append({
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "user_id": user_id,
            "job_id": rw_job_id,
            "final_score": jr.final_score,
            "semantic_score": jr.semantic_score,
            "skills_score": jr.skills_score,
            "company_score": jr.company_score,
            "seniority_score": jr.seniority_score,
            "location_score": jr.location_score,
            "recency_score": jr.recency_score,
            "title_relevance_score": jr.title_relevance_score,
            "fit_band": jr.fit_band,
            "confidence_band": jr.confidence_band,
            "explanation_summary": jr.explanation_summary,
            "match_report": jr.match_report,
            "verification_report": jr.verification_report,
            "company_tier": jr.company_tier,
            "is_contract": jr.is_contract,
        })

    if results_data:
        await railway_db.execute(
            pg_insert(JobResult)
            .values(results_data)
            .on_conflict_do_update(
                constraint="uq_job_results_user_job",
                set_={
                    "final_score": pg_insert(JobResult).excluded.final_score,
                    "semantic_score": pg_insert(JobResult).excluded.semantic_score,
                    "skills_score": pg_insert(JobResult).excluded.skills_score,
                    "company_score": pg_insert(JobResult).excluded.company_score,
                    "seniority_score": pg_insert(JobResult).excluded.seniority_score,
                    "location_score": pg_insert(JobResult).excluded.location_score,
                    "recency_score": pg_insert(JobResult).excluded.recency_score,
                    "title_relevance_score": pg_insert(JobResult).excluded.title_relevance_score,
                    "company_tier": pg_insert(JobResult).excluded.company_tier,
                    "is_contract": pg_insert(JobResult).excluded.is_contract,
                },
            )
        )

    await railway_db.commit()
    logger.info("local_sync: synced %d results for run %s to Railway", len(results_data), run_id)
    return len(results_data)
