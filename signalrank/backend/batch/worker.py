import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobRaw, JobResult, Profile, Run
from batch.context import build_context
from batch.embedding_cache import PgEmbeddingCache
from batch.ranker import score_jobs_for_user

logger = logging.getLogger(__name__)


async def _embed_new_jobs(db: AsyncSession, raw_jobs: list) -> None:
    """Pre-compute and cache embeddings for newly scraped jobs using base config."""
    if not raw_jobs:
        return

    from batch.scraper import raw_job_to_dict
    from domain.embeddings import (
        EmbeddingEngine,
        build_job_embedding_text,
        fingerprint_text,
    )
    from domain.skills import SkillCanonicalizer, extract_skills_from_texts
    import domain.embeddings as _emb_mod

    ctx = build_context(user_id="__base__", resume_text="")
    cfg = ctx.config
    cache = PgEmbeddingCache(db, ctx.config_fp)

    descriptions = [j.description or "" for j in raw_jobs]
    raw_skills_list = extract_skills_from_texts(descriptions, cfg)
    canon = SkillCanonicalizer(cfg)
    canonical_skills_list = [sorted(canon.canonicalize(s)) for s in raw_skills_list]

    job_texts = [
        build_job_embedding_text(
            title=j.title or "",
            description=j.description or "",
            canonical_skills=cs,
            cfg=cfg,
        )
        for j, cs in zip(raw_jobs, canonical_skills_list)
    ]
    job_fps = [fingerprint_text(t) for t in job_texts]
    cached = await cache.fetch(job_fps)

    misses = [i for i, fp in enumerate(job_fps) if fp not in cached]
    if not misses:
        return

    try:
        engine = EmbeddingEngine(cfg)
        new_vecs = engine.embed([job_texts[i] for i in misses])
        await cache.store_vectors(
            [(job_fps[i], v.tolist()) for i, v in zip(misses, new_vecs)]
        )
        await db.commit()
        logger.info("[EMBED] Pre-cached %d job embeddings", len(misses))
    finally:
        if _emb_mod._ENGINE is not None:
            _emb_mod._ENGINE.unload()

_queue: asyncio.Queue | None = None


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=100)
    return _queue


async def process_run(
    run_id: str, user_id: str, session_factory: async_sessionmaker
) -> None:
    async with session_factory() as db:
        try:
            # Check if run was cancelled before it even started
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if run_check and run_check.status == "cancelled":
                logger.info("Run %s was cancelled before starting, skipping", run_id)
                return

            await db.execute(
                update(Run).where(Run.id == run_id).values(status="scraping")
            )
            await db.commit()

            profile_result = await db.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = profile_result.scalar_one_or_none()
            resume_text = profile.resume_text if profile else ""
            distilled_text = profile.distilled_text if profile else None
            config_overrides = profile.config_overrides if profile else None

            from batch.query_builder import build_queries
            from batch.scraper import ScraperConfig, scrape, raw_job_to_dict

            queries = build_queries(profile) if profile else []

            async def _update_progress(**kwargs):
                await db.execute(
                    update(Run).where(Run.id == run_id).values(progress=kwargs)
                )
                await db.commit()

            scrape_count = 0
            if queries:
                title_blocklist = (config_overrides or {}).get("title_blocklist", [])
                config = ScraperConfig.from_env(title_blocklist=title_blocklist)

                # Check cancellation before scraping
                run_check_result = await db.execute(select(Run).where(Run.id == run_id))
                run_check = run_check_result.scalar_one_or_none()
                if run_check and run_check.status == "cancelled":
                    await db.execute(
                        update(Run).where(Run.id == run_id).values(
                            status="cancelled", finished_at=datetime.now(timezone.utc)
                        )
                    )
                    await db.commit()
                    logger.info("Run %s was cancelled before scraping", run_id)
                    return

                raw_jobs = await scrape(queries, config, on_progress=_update_progress)

                # Check cancellation after scraping
                run_check_result = await db.execute(select(Run).where(Run.id == run_id))
                run_check = run_check_result.scalar_one_or_none()
                if run_check and run_check.status == "cancelled":
                    await db.commit()
                    logger.info("Run %s was cancelled after scraping", run_id)
                    return

                if raw_jobs:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    # Batch inserts to stay under PostgreSQL's 65535 bind-param limit
                    # 8 columns per row → max ~8000 rows per batch
                    batch_size = 2000
                    for i in range(0, len(raw_jobs), batch_size):
                        batch = raw_jobs[i:i + batch_size]
                        stmt = pg_insert(JobRaw).values([
                            raw_job_to_dict(job) for job in batch
                        ]).on_conflict_do_nothing(index_elements=["job_url"])
                        await db.execute(stmt)
                    await db.commit()
                scrape_count = len(raw_jobs)

                if raw_jobs:
                    await _embed_new_jobs(db, raw_jobs)

            # Check cancellation before ranking
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if run_check and run_check.status == "cancelled":
                await db.commit()
                logger.info("Run %s was cancelled before ranking", run_id)
                return

            await db.execute(
                update(Run).where(Run.id == run_id).values(
                    status="ranking",
                    scrape_count=scrape_count,
                    progress={"phase": "ranking", "phase_num": 1, "total_phases": 1,
                              "jobs_found": scrape_count, "message": "Ranking jobs..."},
                )
            )
            await db.commit()

            ranked_df = await score_jobs_for_user(
                db=db,
                user_id=user_id,
                resume_text=resume_text,
                distilled_text=distilled_text,
                config_overrides=config_overrides,
            )

            # Check cancellation after ranking (before inserting results)
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if run_check and run_check.status == "cancelled":
                await db.commit()
                logger.info("Run %s was cancelled before saving results", run_id)
                return

            result_rows = [
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "job_id": row["id"],
                    "semantic_score": float(row.get("semantic_score", 0)),
                    "skills_score": float(row.get("skills_score", 0)),
                    "company_score": float(row.get("company_score", 0)),
                    "seniority_score": float(row.get("seniority_score_dim", 0)),
                    "location_score": float(row.get("location_score", 0)),
                    "recency_score": float(row.get("recency_score", 0)),
                    "final_score": float(row.get("final_score", 0)),
                    "company_tier": str(row.get("company_tier", "")),
                    "is_contract": bool(row.get("is_contract", False)),
                }
                for _, row in ranked_df.iterrows()
            ]
            for i in range(0, len(result_rows), 2000):
                await db.execute(
                    pg_insert(JobResult).values(result_rows[i:i + 2000])
                )

            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="success",
                    finished_at=datetime.now(timezone.utc),
                    job_count=len(ranked_df),
                    progress=None,
                )
            )
            await db.commit()
            logger.info("Run %s completed: %d scraped, %d ranked", run_id, scrape_count, len(ranked_df))

        except Exception:
            logger.exception("Run %s failed", run_id)
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="failed", finished_at=datetime.now(timezone.utc), progress=None)
            )
            await db.commit()


async def worker_loop(session_factory: async_sessionmaker) -> None:
    queue = get_queue()
    logger.info("Background worker started")
    while True:
        run_id, user_id = await queue.get()
        try:
            await process_run(run_id, user_id, session_factory)
        finally:
            queue.task_done()
