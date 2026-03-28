import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobRaw, JobResult, Profile, Run
from batch.context import build_context
from batch.embedding_cache import PgEmbeddingCache
from batch.ranker import score_jobs_for_user

logger = logging.getLogger(__name__)


_EMBED_CHUNK_SIZE = 64
_EMBED_MAX_RETRIES = 3
_EMBED_BACKOFF_BASE = 2


async def _embed_new_jobs(
    db: AsyncSession,
    raw_jobs: list,
    update_progress=None,
) -> None:
    """Pre-compute and cache embeddings with retry, chunked saves, and progress."""
    if not raw_jobs:
        return

    from domain.embeddings import (
        EmbeddingEngine,
        build_job_embedding_text,
        fingerprint_text,
    )
    from domain.skills import SkillCanonicalizer, extract_skills_from_texts

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

    for attempt in range(1, _EMBED_MAX_RETRIES + 1):
        try:
            cached = await cache.fetch(job_fps)
            misses = [i for i, fp in enumerate(job_fps) if fp not in cached]
            if not misses:
                logger.info("[EMBED] All %d embeddings cached, skipping", len(job_fps))
                return

            logger.info(
                "[EMBED] %d cache hits, %d misses (attempt %d/%d)",
                len(job_fps) - len(misses), len(misses), attempt, _EMBED_MAX_RETRIES,
            )

            engine = EmbeddingEngine(cfg)
            miss_texts = [job_texts[i] for i in misses]
            total = len(miss_texts)

            embedded = 0
            for chunk_start in range(0, total, _EMBED_CHUNK_SIZE):
                chunk_end = min(chunk_start + _EMBED_CHUNK_SIZE, total)
                chunk_texts = miss_texts[chunk_start:chunk_end]
                chunk_indices = misses[chunk_start:chunk_end]

                vecs = await asyncio.to_thread(engine.embed, chunk_texts)

                await cache.store_vectors(
                    [(job_fps[i], v.tolist()) for i, v in zip(chunk_indices, vecs)]
                )
                await db.commit()

                embedded = chunk_end
                if update_progress:
                    await update_progress(
                        phase="embedding",
                        phase_num=0,
                        total_phases=1,
                        jobs_found=len(raw_jobs),
                        message=f"Embedding jobs: {embedded}/{total}",
                    )

            logger.info("[EMBED] Pre-cached %d job embeddings", total)
            return

        except Exception:
            logger.warning(
                "[EMBED] Attempt %d/%d failed", attempt, _EMBED_MAX_RETRIES,
                exc_info=True,
            )
            if attempt < _EMBED_MAX_RETRIES:
                delay = _EMBED_BACKOFF_BASE ** attempt
                logger.info("[EMBED] Retrying in %ds...", delay)
                await asyncio.sleep(delay)
            else:
                logger.error("[EMBED] All %d attempts failed, continuing without full cache", _EMBED_MAX_RETRIES)

_queue: asyncio.Queue | None = None


def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=100)
    return _queue


async def process_run(
    run_id: str, user_id: str, session_factory: async_sessionmaker,
    mode: str = "quick",
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

            if mode == "quick":
                scraper_max_terms = 1
                scraper_hours_old = 24
            else:
                scraper_max_terms = profile.scraper_max_terms if profile else None
                scraper_hours_old = profile.scraper_hours_old or 168  # 7 days
            queries = build_queries(profile, max_terms=scraper_max_terms) if profile else []

            async def _update_progress(**kwargs):
                async with session_factory() as pdb:
                    await pdb.execute(
                        update(Run).where(Run.id == run_id).values(progress=kwargs)
                    )
                    await pdb.commit()

            # Skip scraping if a recent successful scrape already ran
            scrape_threshold_hours = 1 if mode == "quick" else 6
            scrape_cutoff = datetime.now(timezone.utc) - timedelta(hours=scrape_threshold_hours)
            recent_scrape = await db.execute(
                select(Run).where(
                    Run.user_id == user_id,
                    Run.status == "success",
                    Run.scrape_count > 0,
                    Run.finished_at >= scrape_cutoff,
                    Run.id != run_id,
                )
            )
            skip_scrape = recent_scrape.scalar_one_or_none() is not None
            if skip_scrape:
                logger.info(
                    "Run %s skipping scrape — recent scrape within %dh threshold",
                    run_id, scrape_threshold_hours,
                )

            scrape_count = 0
            if queries and not skip_scrape:
                title_blocklist = (config_overrides or {}).get("title_blocklist", [])
                config = ScraperConfig.from_env(title_blocklist=title_blocklist)
                config.hours_old = scraper_hours_old
                if mode == "quick":
                    config.sources = ["indeed"]

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

                async def _persist_jobs(jobs):
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    async with session_factory() as pdb:
                        batch_size = 2000
                        for i in range(0, len(jobs), batch_size):
                            batch = jobs[i:i + batch_size]
                            stmt = pg_insert(JobRaw).values([
                                raw_job_to_dict(job) for job in batch
                            ]).on_conflict_do_nothing(index_elements=["job_url"])
                            await pdb.execute(stmt)
                        await pdb.commit()

                t_scrape = time.monotonic()
                raw_jobs = await scrape(queries, config, on_progress=_update_progress, on_persist=_persist_jobs)
                logger.info("Run %s scrape done", run_id,
                            extra={"run_id": run_id, "phase": "scrape",
                                   "duration_s": round(time.monotonic() - t_scrape, 1),
                                   "jobs_found": len(raw_jobs)})

                # Check cancellation after scraping
                run_check_result = await db.execute(select(Run).where(Run.id == run_id))
                run_check = run_check_result.scalar_one_or_none()
                if run_check and run_check.status == "cancelled":
                    await db.commit()
                    logger.info("Run %s was cancelled after scraping", run_id)
                    return

                scrape_count = len(raw_jobs)

                if raw_jobs:
                    t_embed = time.monotonic()
                    await _embed_new_jobs(db, raw_jobs, update_progress=_update_progress)
                    logger.info("Run %s embed done", run_id,
                                extra={"run_id": run_id, "phase": "embed",
                                       "duration_s": round(time.monotonic() - t_embed, 1),
                                       "jobs": len(raw_jobs)})

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

            t_rank = time.monotonic()
            try:
                ranked_df = await asyncio.wait_for(
                    score_jobs_for_user(
                        db=db,
                        user_id=user_id,
                        resume_text=resume_text,
                        distilled_text=distilled_text,
                        config_overrides=config_overrides,
                    ),
                    timeout=600,  # 10 min max
                )
            except asyncio.TimeoutError:
                logger.error("Run %s ranking timed out after 600s", run_id)
                await db.execute(
                    update(Run).where(Run.id == run_id).values(
                        status="failed", finished_at=datetime.now(timezone.utc),
                        progress=None,
                    )
                )
                await db.commit()
                return
            logger.info("Run %s ranking done in %.1fs, %d jobs",
                        run_id, time.monotonic() - t_rank, len(ranked_df))

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
                for row in ranked_df.to_dict("records")
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
            logger.info("Run %s (%s) completed: %d scraped, %d ranked", run_id, mode, scrape_count, len(ranked_df))

            if mode == "quick":
                bg_run = Run(user_id=user_id, status="pending")
                db.add(bg_run)
                await db.commit()
                await db.refresh(bg_run)
                queue = get_queue()
                await queue.put((bg_run.id, user_id, "full"))
                logger.info("Queued background full run %s after quick run %s", bg_run.id, run_id)

        except Exception:
            logger.exception("Run %s failed", run_id)
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="failed", finished_at=datetime.now(timezone.utc), progress=None)
            )
            await db.commit()


async def boot_embed_uncached_jobs(session_factory: async_sessionmaker) -> None:
    """Pre-embed any job_raw rows not yet in the __base__ embedding cache."""
    from api.models import JobRaw
    from batch.context import build_context
    from datetime import timedelta

    async with session_factory() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        result = await db.execute(
            select(JobRaw.id, JobRaw.title, JobRaw.description)
            .where(JobRaw.ingested_at >= cutoff)
        )
        rows = result.all()

    if not rows:
        return

    from domain.embeddings import build_job_embedding_text, fingerprint_text
    from domain.skills import SkillCanonicalizer, extract_skills_from_texts

    ctx = build_context(user_id="__base__", resume_text="")
    cfg = ctx.config
    canon = SkillCanonicalizer(cfg)

    descriptions = [r.description or "" for r in rows]
    raw_skills_list = extract_skills_from_texts(descriptions, cfg)
    canonical_skills_list = [sorted(canon.canonicalize(s)) for s in raw_skills_list]

    job_texts = [
        build_job_embedding_text(
            title=r.title or "",
            description=r.description or "",
            canonical_skills=cs,
            cfg=cfg,
        )
        for r, cs in zip(rows, canonical_skills_list)
    ]
    job_fps = [fingerprint_text(t) for t in job_texts]

    async with session_factory() as db:
        cache = PgEmbeddingCache(db, ctx.config_fp)
        cached = await cache.fetch(job_fps)
        misses = [i for i, fp in enumerate(job_fps) if fp not in cached]

    if not misses:
        logger.info("[BOOT-EMBED] All %d job embeddings cached", len(job_fps))
        return

    logger.info("[BOOT-EMBED] Pre-embedding %d/%d uncached jobs", len(misses), len(job_fps))
    from domain.embeddings import EmbeddingEngine
    engine = EmbeddingEngine(cfg)
    total = len(misses)

    for chunk_start in range(0, total, _EMBED_CHUNK_SIZE):
        chunk_end = min(chunk_start + _EMBED_CHUNK_SIZE, total)
        chunk_indices = misses[chunk_start:chunk_end]
        chunk_texts = [job_texts[i] for i in chunk_indices]

        vecs = await asyncio.to_thread(engine.embed, chunk_texts)

        async with session_factory() as db:
            cache = PgEmbeddingCache(db, ctx.config_fp)
            await cache.store_vectors(
                [(job_fps[i], v.tolist()) for i, v in zip(chunk_indices, vecs)]
            )
            await db.commit()

        if chunk_end % 500 == 0 or chunk_end == total:
            logger.info("[BOOT-EMBED] %d/%d", chunk_end, total)

    logger.info("[BOOT-EMBED] Done — pre-cached %d job embeddings", total)


async def _cleanup_stale_runs(session_factory: async_sessionmaker) -> None:
    async with session_factory() as db:
        stale = await db.execute(
            select(Run).where(Run.status.in_(["pending", "scraping", "ranking"]))
        )
        for run in stale.scalars().all():
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.progress = None
            logger.warning("Marked stale run %s as failed", run.id)
        await db.commit()


async def worker_loop(session_factory: async_sessionmaker) -> None:
    queue = get_queue()
    await _cleanup_stale_runs(session_factory)
    logger.info("Background worker started")
    while True:
        item = await queue.get()
        if len(item) == 3:
            run_id, user_id, mode = item
        else:
            run_id, user_id = item
            mode = "quick"
        try:
            await process_run(run_id, user_id, session_factory, mode=mode)
        finally:
            queue.task_done()
