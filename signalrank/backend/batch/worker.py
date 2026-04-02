import asyncio
import gc
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobRaw, JobResult, Profile, Run
from batch.context import build_context, get_batch, get_retry
from batch.embedding_cache import PgEmbeddingCache, clear_vector_cache, store_job_embeddings
from batch.memory import log_rss, release_memory

logger = logging.getLogger(__name__)

_TRANSIENT_EXCEPTIONS = (asyncio.TimeoutError, ConnectionError, OSError)
_RUN_MAX_RETRIES = 3
_RUN_BACKOFF_BASE = 2  # seconds: 2, 4, 8


@dataclass
class RunRequest:
    run_id: str
    user_id: str
    mode: str = "quick"
    force_scrape: bool = False


def _should_log_embed_progress(done: int, total: int, last_logged: int) -> bool:
    if done >= total:
        return True
    if total <= 100:
        return done != last_logged
    step = max(100, total // 20)
    return (done // step) > (last_logged // step)




def _format_run_error(exc: Exception) -> str:
    message = f"{exc.__class__.__name__}: {exc}".strip()
    return message[:1000]


def _run_progress_meta(mode: str, force_scrape: bool, *, scrape_executed: bool | None = None) -> dict:
    progress = {
        "requested_mode": mode,
        "force_scrape": force_scrape,
    }
    if scrape_executed is not None:
        progress["scrape_executed"] = scrape_executed
    return progress


def _merge_run_progress(mode: str, force_scrape: bool, *, scrape_executed: bool | None = None, **kwargs) -> dict:
    progress = _run_progress_meta(mode, force_scrape, scrape_executed=scrape_executed)
    progress.update(kwargs)
    return progress


async def _embed_new_jobs(
    db: AsyncSession,
    job_urls: list[str],
    update_progress=None,
) -> None:
    """Pre-compute and cache embeddings by re-reading persisted jobs in small chunks."""
    if not job_urls:
        return

    from domain.embeddings import (
        EmbeddingEngine,
        build_job_embedding_text,
        fingerprint_text,
        unload_embedding_engine,
    )
    from domain.skills import SkillCanonicalizer, extract_skills_from_texts

    ctx = build_context(user_id="__base__", resume_text="")
    cfg = ctx.config
    cache = PgEmbeddingCache(db, ctx.config_fp)

    embed_max_retries = get_retry(cfg, "embed_max", 3)
    embed_chunk_size = get_batch(cfg, "embed_chunk_size", 4)
    embed_backoff_base = get_retry(cfg, "embed_backoff_base", 2)
    total_jobs = len(job_urls)
    canon = SkillCanonicalizer(cfg)

    for attempt in range(1, embed_max_retries + 1):
        try:
            logger.info("[EMBED] Preparing %d persisted jobs (attempt %d/%d)", total_jobs, attempt, embed_max_retries)
            log_rss(logger, "embed_prepare", total_jobs=total_jobs)

            engine = None
            cache_hits = 0
            cache_misses = 0
            processed = 0
            last_logged = 0

            for chunk_start in range(0, total_jobs, embed_chunk_size):
                chunk_urls = job_urls[chunk_start:chunk_start + embed_chunk_size]
                result = await db.execute(
                    select(JobRaw.job_url, JobRaw.title, JobRaw.description).where(JobRaw.job_url.in_(chunk_urls))
                )
                rows = result.all()
                if not rows:
                    processed += len(chunk_urls)
                    continue

                rows_by_url = {row.job_url: row for row in rows}
                ordered_rows = [rows_by_url[url] for url in chunk_urls if url in rows_by_url]
                descriptions = [row.description or "" for row in ordered_rows]
                raw_skills_list = extract_skills_from_texts(descriptions, cfg)
                chunk_specs: list[tuple[str, str, str]] = []
                for row, raw_skills in zip(ordered_rows, raw_skills_list):
                    canonical_skills = sorted(canon.canonicalize(raw_skills))
                    job_text = build_job_embedding_text(
                        title=row.title or "",
                        description=row.description or "",
                        canonical_skills=canonical_skills,
                        cfg=cfg,
                    )
                    chunk_specs.append((row.job_url, fingerprint_text(job_text), job_text))

                cached = await cache.fetch([text_fp for _, text_fp, _ in chunk_specs])
                cached_job_rows: list[tuple[str, list[float]]] = []
                miss_specs: list[tuple[str, str, str]] = []
                for job_url, text_fp, job_text in chunk_specs:
                    vector = cached.get(text_fp)
                    if vector is None:
                        miss_specs.append((job_url, text_fp, job_text))
                        cache_misses += 1
                    else:
                        cached_job_rows.append((job_url, vector))
                        cache_hits += 1

                if cached_job_rows:
                    await store_job_embeddings(db, cached_job_rows)
                    await db.commit()

                if miss_specs:
                    if engine is None:
                        engine = EmbeddingEngine(cfg)
                    vecs = await asyncio.to_thread(engine.embed, [job_text for _, _, job_text in miss_specs])
                    cache_rows: list[tuple[str, list[float]]] = []
                    job_embedding_rows: list[tuple[str, list[float]]] = []
                    for (job_url, text_fp, _), vector in zip(miss_specs, vecs):
                        clean_vector = vector.tolist()
                        cache_rows.append((text_fp, clean_vector))
                        job_embedding_rows.append((job_url, clean_vector))
                    await cache.store_vectors(cache_rows)
                    await store_job_embeddings(db, job_embedding_rows)
                    await db.commit()

                processed += len(ordered_rows)
                if _should_log_embed_progress(processed, total_jobs, last_logged):
                    logger.info("[EMBED] Encoded %d/%d persisted jobs", processed, total_jobs)
                    last_logged = processed
                    log_rss(logger, "embed_progress", encoded=processed, total=total_jobs)
                if update_progress:
                    await update_progress(
                        phase="embedding",
                        phase_num=0,
                        total_phases=1,
                        jobs_found=total_jobs,
                        message=f"Embedding jobs: {processed}/{total_jobs}",
                    )
                del rows, ordered_rows, rows_by_url, descriptions, raw_skills_list, chunk_specs
                if "vecs" in locals():
                    del vecs
                gc.collect()

            logger.info(
                "[EMBED] Completed persisted embedding pass: %d cache hits, %d misses",
                cache_hits,
                cache_misses,
            )
            unload_embedding_engine()
            clear_vector_cache()
            release_memory(logger, "embed_release", total_jobs=total_jobs, cache_misses=cache_misses)
            return

        except Exception:
            logger.warning(
                "[EMBED] Attempt %d/%d failed", attempt, embed_max_retries,
                exc_info=True,
            )
            if attempt < embed_max_retries:
                delay = embed_backoff_base ** attempt
                logger.info("[EMBED] Retrying in %ds...", delay)
                await asyncio.sleep(delay)
            else:
                logger.error("[EMBED] All %d attempts failed, continuing without full cache", embed_max_retries)
    try:
        unload_embedding_engine()
    except Exception:
        logger.debug("[EMBED] Engine unload skipped", exc_info=True)
    clear_vector_cache()
    release_memory(logger, "embed_release_error")

_queues: dict[str, asyncio.Queue] = {}


def get_queue(mode: str = "quick") -> asyncio.Queue:
    if mode not in _queues:
        _queues[mode] = asyncio.Queue(maxsize=100)
    return _queues[mode]


async def process_run(
    run_id: str, user_id: str, session_factory: async_sessionmaker,
    mode: str = "quick",
    force_scrape: bool = False,
) -> None:
    async with session_factory() as db:
        scrape_executed = False
        try:
            log_rss(logger, "run_start", run_id=run_id, user_id=user_id, mode=mode)
            # Check if run was cancelled before it even started
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if not run_check or run_check.status == "cancelled":
                logger.info("Run %s not found or cancelled before starting, skipping", run_id)
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
                        update(Run).where(Run.id == run_id).values(
                            progress=_merge_run_progress(
                                mode,
                                force_scrape,
                                scrape_executed=scrape_executed,
                                **kwargs,
                            )
                        )
                    )
                    await pdb.commit()

            now = datetime.now(timezone.utc)
            skip_scrape = False
            if not force_scrape:
                if mode == "full":
                    deep_scan_cutoff = now - timedelta(hours=48)
                    recent_runs_result = await db.execute(
                        select(Run).where(
                            Run.user_id == user_id,
                            Run.status == "success",
                            Run.finished_at >= deep_scan_cutoff,
                            Run.id != run_id,
                        ).order_by(Run.finished_at.desc()).limit(20)
                    )
                    recent_runs = recent_runs_result.scalars().all()
                    skip_scrape = any(
                        recent_run.mode == "full"
                        and isinstance(recent_run.progress, dict)
                        and recent_run.progress.get("scrape_executed") is True
                        for recent_run in recent_runs
                    )
                    scrape_threshold_hours = 48
                else:
                    scrape_threshold_hours = 1
                    scrape_cutoff = now - timedelta(hours=scrape_threshold_hours)
                    recent_scrape = await db.execute(
                        select(Run.id).where(
                            Run.user_id == user_id,
                            Run.status == "success",
                            Run.scrape_count.is_not(None),
                            Run.finished_at >= scrape_cutoff,
                            Run.id != run_id,
                        ).limit(1)
                    )
                    skip_scrape = recent_scrape.scalar_one_or_none() is not None
            if skip_scrape:
                logger.info(
                    "Run %s skipping scrape — recent scrape within %dh threshold",
                    run_id, scrape_threshold_hours,
                )

            scrape_count = 0
            freshly_scraped_job_urls = None
            if queries and not skip_scrape:
                scrape_executed = True
                title_blocklist = (config_overrides or {}).get("title_blocklist", [])
                config = ScraperConfig.from_env(title_blocklist=title_blocklist)
                config.hours_old = scraper_hours_old
                if mode == "quick":
                    config.sources = ["indeed"]

                # Check cancellation before scraping
                run_check_result = await db.execute(select(Run).where(Run.id == run_id))
                run_check = run_check_result.scalar_one_or_none()
                if not run_check or run_check.status == "cancelled":
                    if run_check:
                        await db.execute(
                            update(Run).where(Run.id == run_id).values(
                                status="cancelled", finished_at=datetime.now(timezone.utc)
                            )
                        )
                        await db.commit()
                    logger.info("Run %s not found or cancelled before scraping", run_id)
                    return

                async def _persist_jobs(jobs):
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    from domain.role_clusters import infer_clusters_from_job_text
                    async with session_factory() as pdb:
                        batch_size = 2000
                        for i in range(0, len(jobs), batch_size):
                            batch = jobs[i:i + batch_size]
                            values = [raw_job_to_dict(job) for job in batch]
                            for v in values:
                                v["role_clusters"] = sorted(
                                    infer_clusters_from_job_text(v.get("title"), v.get("description")) - {"general"}
                                )
                            insert_stmt = pg_insert(JobRaw).values(values)
                            stmt = (
                                insert_stmt
                                .on_conflict_do_update(
                                    index_elements=["job_url"],
                                    set_={
                                        "role_clusters": insert_stmt.excluded.role_clusters,
                                    },
                                )
                            )
                            await pdb.execute(stmt)
                        await pdb.commit()

                t_scrape = time.monotonic()
                scraped_job_urls = await scrape(
                    queries,
                    config,
                    on_progress=_update_progress,
                    on_persist=_persist_jobs,
                    return_mode="urls",
                )
                logger.info("Run %s scrape done", run_id,
                            extra={"run_id": run_id, "phase": "scrape",
                                   "duration_s": round(time.monotonic() - t_scrape, 1),
                                   "jobs_found": len(scraped_job_urls)})
                log_rss(logger, "after_scrape", run_id=run_id, jobs_found=len(scraped_job_urls))

                # Check cancellation after scraping
                run_check_result = await db.execute(select(Run).where(Run.id == run_id))
                run_check = run_check_result.scalar_one_or_none()
                if not run_check or run_check.status == "cancelled":
                    logger.info("Run %s not found or cancelled after scraping", run_id)
                    return

                scrape_count = len(scraped_job_urls)

                # Track URLs of newly scraped jobs for ranking against fresh results only
                freshly_scraped_job_urls = scraped_job_urls if scraped_job_urls else None
                if freshly_scraped_job_urls:
                    logger.info("Run %s will rank against %d freshly scraped job URLs (filtered mode)",
                                run_id, len(freshly_scraped_job_urls))

                if scraped_job_urls:
                    t_embed = time.monotonic()
                    await _embed_new_jobs(db, scraped_job_urls, update_progress=_update_progress)
                    logger.info("Run %s embed done", run_id,
                                extra={"run_id": run_id, "phase": "embed",
                                       "duration_s": round(time.monotonic() - t_embed, 1),
                                       "jobs": len(scraped_job_urls)})
                    log_rss(logger, "after_embed", run_id=run_id, jobs=len(scraped_job_urls))
                    del scraped_job_urls
                    release_memory(logger, "after_embed_release", run_id=run_id)

            # Check cancellation before ranking
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if not run_check or run_check.status == "cancelled":
                logger.info("Run %s not found or cancelled before ranking", run_id)
                return

            await db.execute(
                update(Run).where(Run.id == run_id).values(
                    status="ranking",
                    scrape_count=scrape_count,
                    progress=_merge_run_progress(
                        mode,
                        force_scrape,
                        scrape_executed=scrape_executed,
                        phase="ranking",
                        phase_num=1,
                        total_phases=1,
                        jobs_found=scrape_count,
                        message="Ranking jobs...",
                    ),
                )
            )
            await db.commit()
            log_rss(logger, "before_rank", run_id=run_id, scrape_count=scrape_count)

            t_rank = time.monotonic()
            try:
                from batch.ranker import score_jobs_for_user
                ranked_df = await asyncio.wait_for(
                    score_jobs_for_user(
                        db=db,
                        user_id=user_id,
                        resume_text=resume_text,
                        distilled_text=distilled_text,
                        config_overrides=config_overrides,
                        job_urls=freshly_scraped_job_urls,
                    ),
                    timeout=600,  # 10 min max
                )
            except asyncio.TimeoutError:
                logger.error("Run %s ranking timed out after 600s", run_id)
                await db.execute(
                    update(Run).where(Run.id == run_id).values(
                        status="failed", finished_at=datetime.now(timezone.utc),
                        progress=_run_progress_meta(mode, force_scrape, scrape_executed=scrape_executed),
                        error="TimeoutError: Ranking timed out after 600s",
                    )
                )
                await db.commit()
                return
            logger.info("Run %s ranking done in %.1fs, %d jobs",
                        run_id, time.monotonic() - t_rank, len(ranked_df))
            log_rss(logger, "after_rank", run_id=run_id, ranked_jobs=len(ranked_df))

            # Check cancellation after ranking (before inserting results)
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if not run_check or run_check.status == "cancelled":
                logger.info("Run %s not found or cancelled before saving results", run_id)
                return

            insert_batch: list[dict] = []
            for row in ranked_df.itertuples(index=False):
                insert_batch.append({
                    "run_id": run_id,
                    "user_id": user_id,
                    "job_id": row.id,
                    "semantic_score": float(row.semantic_score or 0),
                    "skills_score": float(row.skills_score or 0),
                    "company_score": float(row.company_score or 0),
                    "seniority_score": float(row.seniority_score_dim or 0),
                    "location_score": float(row.location_score or 0),
                    "recency_score": float(row.recency_score or 0),
                    "final_score": float(row.final_score or 0),
                    "title_relevance_score": float(getattr(row, "title_relevance_score", None) or 0),
                    "company_tier": str(row.company_tier or ""),
                    "is_contract": bool(row.is_contract),
                })
                if len(insert_batch) >= 500:
                    await db.execute(
                        pg_insert(JobResult).values(insert_batch).on_conflict_do_update(
                            constraint="uq_job_results_user_job",
                            set_={
                                "run_id": pg_insert(JobResult).excluded.run_id,
                                "semantic_score": pg_insert(JobResult).excluded.semantic_score,
                                "skills_score": pg_insert(JobResult).excluded.skills_score,
                                "company_score": pg_insert(JobResult).excluded.company_score,
                                "seniority_score": pg_insert(JobResult).excluded.seniority_score,
                                "location_score": pg_insert(JobResult).excluded.location_score,
                                "recency_score": pg_insert(JobResult).excluded.recency_score,
                                "final_score": pg_insert(JobResult).excluded.final_score,
                                "title_relevance_score": pg_insert(JobResult).excluded.title_relevance_score,
                                "company_tier": pg_insert(JobResult).excluded.company_tier,
                                "is_contract": pg_insert(JobResult).excluded.is_contract,
                            },
                        )
                    )
                    insert_batch.clear()
            if insert_batch:
                await db.execute(
                    pg_insert(JobResult).values(insert_batch).on_conflict_do_update(
                        constraint="uq_job_results_user_job",
                        set_={
                            "run_id": pg_insert(JobResult).excluded.run_id,
                            "semantic_score": pg_insert(JobResult).excluded.semantic_score,
                            "skills_score": pg_insert(JobResult).excluded.skills_score,
                            "company_score": pg_insert(JobResult).excluded.company_score,
                            "seniority_score": pg_insert(JobResult).excluded.seniority_score,
                            "location_score": pg_insert(JobResult).excluded.location_score,
                            "recency_score": pg_insert(JobResult).excluded.recency_score,
                            "final_score": pg_insert(JobResult).excluded.final_score,
                            "title_relevance_score": pg_insert(JobResult).excluded.title_relevance_score,
                            "company_tier": pg_insert(JobResult).excluded.company_tier,
                            "is_contract": pg_insert(JobResult).excluded.is_contract,
                        },
                    )
                )
                insert_batch.clear()
            release_memory(logger, "result_rows_release", run_id=run_id)

            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="success",
                    finished_at=datetime.now(timezone.utc),
                    job_count=len(ranked_df),
                    progress=_run_progress_meta(mode, force_scrape, scrape_executed=scrape_executed),
                    error=None,
                )
            )
            await db.commit()
            logger.info("Run %s (%s) completed: %d scraped, %d ranked", run_id, mode, scrape_count, len(ranked_df))
            del ranked_df
            clear_vector_cache()
            release_memory(logger, "run_complete_release", run_id=run_id, mode=mode)

        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            try:
                await db.rollback()
                await db.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="failed",
                        finished_at=datetime.now(timezone.utc),
                        progress=_run_progress_meta(mode, force_scrape, scrape_executed=scrape_executed),
                        error=_format_run_error(exc),
                    )
                )
                await db.commit()
            except Exception:
                logger.warning("Run %s: failed to update status after error", run_id, exc_info=True)


async def boot_embed_uncached_jobs(session_factory: async_sessionmaker) -> None:
    """Pre-embed any job_raw rows not yet in the __base__ embedding cache."""
    from api.models import JobRaw
    from batch.context import build_context
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=15)
    ctx = build_context(user_id="__base__", resume_text="")
    cfg = ctx.config
    page_size = get_batch(cfg, "boot_embed_page_size", 512)

    async with session_factory() as db:
        total_recent = (
            await db.execute(
                select(func.count()).select_from(JobRaw).where(JobRaw.ingested_at >= cutoff)
            )
        ).scalar_one()
        total_missing = (
            await db.execute(
                select(func.count()).select_from(JobRaw).where(
                    JobRaw.ingested_at >= cutoff,
                    JobRaw.embedding.is_(None),
                )
            )
        ).scalar_one()

    if not total_recent:
        return
    if not total_missing:
        logger.info("[BOOT-EMBED] All %d recent jobs already have stored embeddings", total_recent)
        return

    logger.info("[BOOT-EMBED] Pre-embedding %d/%d uncached jobs", total_missing, total_recent)
    log_rss(logger, "boot_embed_start", total_recent=total_recent, total_missing=total_missing)

    from domain.embeddings import EmbeddingEngine, build_job_embedding_text, fingerprint_text, unload_embedding_engine
    from domain.skills import SkillCanonicalizer, extract_skills_from_texts

    canon = SkillCanonicalizer(cfg)
    engine = EmbeddingEngine(cfg)
    embed_chunk_size = get_batch(cfg, "embed_chunk_size", 4)
    completed = 0
    last_logged = 0

    while True:
        async with session_factory() as db:
            result = await db.execute(
                select(JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.description)
                .where(JobRaw.ingested_at >= cutoff, JobRaw.embedding.is_(None))
                .order_by(JobRaw.ingested_at.desc(), JobRaw.id.desc())
                .limit(page_size)
            )
            rows = result.all()

            if not rows:
                break

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

            cache = PgEmbeddingCache(db, ctx.config_fp)
            cached = await cache.fetch(job_fps)
            misses = [i for i, fp in enumerate(job_fps) if fp not in cached]
            cached_job_rows = [
                (rows[i].job_url, cached[fp])
                for i, fp in enumerate(job_fps)
                if fp in cached
            ]
            if cached_job_rows:
                await store_job_embeddings(db, cached_job_rows)
                await db.commit()

            for chunk_start in range(0, len(misses), embed_chunk_size):
                chunk_end = min(chunk_start + embed_chunk_size, len(misses))
                chunk_indices = misses[chunk_start:chunk_end]
                chunk_texts = [job_texts[i] for i in chunk_indices]
                vecs = await asyncio.to_thread(engine.embed, chunk_texts)

                cache_rows: list[tuple[str, list[float]]] = []
                job_embedding_rows: list[tuple[str, list[float]]] = []
                for i, v in zip(chunk_indices, vecs):
                    vector = v.tolist()
                    cache_rows.append((job_fps[i], vector))
                    job_embedding_rows.append((rows[i].job_url, vector))

                await cache.store_vectors(cache_rows)
                await store_job_embeddings(db, job_embedding_rows)
                await db.commit()

                completed += len(chunk_indices)
                if _should_log_embed_progress(completed, total_missing, last_logged):
                    logger.info("[BOOT-EMBED] Encoded %d/%d uncached jobs", completed, total_missing)
                    log_rss(logger, "boot_embed_progress", encoded=completed, total=total_missing)
                    last_logged = completed

            del rows, descriptions, raw_skills_list, canonical_skills_list, job_texts, job_fps, cached, misses
            gc.collect()

    logger.info("[BOOT-EMBED] Done — pre-cached %d job embeddings", completed)
    unload_embedding_engine()
    gc.collect()


async def _cleanup_stale_runs(session_factory: async_sessionmaker) -> None:
    async with session_factory() as db:
        stale = await db.execute(
            select(Run).where(Run.status.in_(["scraping", "ranking"]))
        )
        for run in stale.scalars().all():
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.progress = None
            run.error = "Worker interrupted before run completion"
            logger.warning("Marked stale run %s as failed", run.id)
        await db.commit()


async def _claim_pending_run(session_factory: async_sessionmaker, mode: str) -> RunRequest | None:
    """Claim the oldest pending run of the given mode, only if no run of that mode is already active.

    This enforces at most 1 quick scan and at most 1 full scan running at any time, globally across
    all users and all worker processes.
    """
    async with session_factory() as db:
        # DB-level guard: don't claim if a run of this mode is already active.
        active_count = await db.scalar(
            select(func.count(Run.id)).where(
                Run.status.in_(["scraping", "ranking", "embedding", "running"]),
                Run.mode == mode,
            )
        )
        if active_count:
            await db.rollback()
            return None

        # Quick scans take priority: if any quick scan is pending, defer full scans.
        if mode == "full":
            quick_pending = await db.scalar(
                select(func.count(Run.id)).where(
                    Run.status == "pending",
                    Run.mode == "quick",
                )
            )
            if quick_pending:
                await db.rollback()
                return None

        result = await db.execute(
            select(Run)
            .where(
                Run.status == "pending",
                Run.mode == mode,
            )
            .order_by(Run.started_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = result.scalar_one_or_none()
        if not run:
            await db.rollback()
            return None

        progress = run.progress if isinstance(run.progress, dict) else {}
        force_scrape = bool(progress.get("force_scrape", False))
        run.status = "scraping"
        await db.commit()
        logger.info(
            "Claimed pending %s run %s from DB poll (user_id=%s force_scrape=%s)",
            mode, run.id, run.user_id, force_scrape,
        )
        return RunRequest(str(run.id), str(run.user_id), mode, force_scrape)


async def _worker_loop_for_mode(session_factory: async_sessionmaker, mode: str) -> None:
    """Poll and process runs of a single mode serially.

    At most one quick scan and one full scan can run at any time (enforced by
    _claim_pending_run). Both mode loops run concurrently inside worker_loop,
    so a quick scan and a full scan can execute in parallel, but two quick scans
    or two full scans never overlap.
    """
    queue = get_queue(mode)
    logger.info("Worker loop started for mode=%s", mode)
    log_rss(logger, "worker_loop_started", mode=mode)
    while True:
        item = None
        from_queue = False
        try:
            item = await asyncio.wait_for(queue.get(), timeout=5)
            from_queue = True
        except asyncio.TimeoutError:
            item = await _claim_pending_run(session_factory, mode)
            if item is None:
                continue

        if isinstance(item, RunRequest):
            req = item
        elif len(item) == 4:
            req = RunRequest(*item)
        elif len(item) == 3:
            req = RunRequest(item[0], item[1], item[2])
        else:
            req = RunRequest(item[0], item[1])

        if from_queue:
            logger.info(
                "Dequeued %s run %s from in-process queue (user_id=%s force_scrape=%s)",
                mode, req.run_id, req.user_id, req.force_scrape,
            )
        try:
            for attempt in range(1, _RUN_MAX_RETRIES + 1):
                try:
                    await process_run(req.run_id, req.user_id, session_factory, mode=req.mode, force_scrape=req.force_scrape)
                    break
                except _TRANSIENT_EXCEPTIONS as exc:
                    if attempt < _RUN_MAX_RETRIES:
                        delay = _RUN_BACKOFF_BASE ** attempt
                        logger.warning(
                            "Run %s transient failure (attempt %d/%d), retrying in %ds: %s",
                            req.run_id, attempt, _RUN_MAX_RETRIES, delay, exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("Run %s failed after %d attempts: %s", req.run_id, _RUN_MAX_RETRIES, exc)
        finally:
            if from_queue:
                queue.task_done()


async def worker_loop(session_factory: async_sessionmaker) -> None:
    """Start one worker loop per scan mode and run them concurrently."""
    await _cleanup_stale_runs(session_factory)
    logger.info("Background worker started")
    await asyncio.gather(
        _worker_loop_for_mode(session_factory, "quick"),
        _worker_loop_for_mode(session_factory, "full"),
    )
