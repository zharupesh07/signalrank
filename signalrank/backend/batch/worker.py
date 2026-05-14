import asyncio
import gc
import logging
import os
import re
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.config import is_desktop_mode, settings
from api.models import JobRaw, Profile, Run
from api.sql_compat import dialect_name
from batch.context import build_context, get_batch, get_retry
from batch.job_availability import archive_expired_jobs_for_user
from batch.run_corpus import load_rerank_corpus_job_urls
from batch.embedding_cache import PgEmbeddingCache, clear_vector_cache, store_job_embeddings
from batch.memory import log_rss, release_memory
from batch.run_progress import corpus_progress, merge_run_progress, run_progress_meta
from batch.run_results import normalize_ranked_df, persist_ranked_results
from batch.run_state import mark_run_cancelled, mark_run_failed
from batch.scrape_pipeline import ScrapePipelineStopRequested, execute_scrape_pipeline
from domain.candidate_profile import build_candidate_profile

logger = logging.getLogger(__name__)

_TRANSIENT_EXCEPTIONS = (asyncio.TimeoutError, ConnectionError, OSError)
_RUN_MAX_RETRIES = 3
_RUN_BACKOFF_BASE = 2  # seconds: 2, 4, 8
_RUN_LEASE_SECONDS = 15 * 60


@dataclass
class RunRequest:
    run_id: str
    user_id: str
    mode: str = "quick"
    force_scrape: bool = False
    disable_scraping: bool = False
    claim_token: str | None = None


def _get_score_jobs_for_user():
    from ranking.v4.db_scorer import score_jobs_for_user

    return score_jobs_for_user


def _should_archive_availability_after_run(ranked_count: int) -> bool:
    return (
        settings.job_availability_archive_after_run
        and not is_desktop_mode()
        and ranked_count > 0
    )


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

def _worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _lease_until(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(seconds=_RUN_LEASE_SECONDS)


async def _update_run_row(
    session_factory: async_sessionmaker,
    run_id: str,
    *,
    values: dict,
    claim_token: str | None = None,
) -> bool:
    async with session_factory() as db:
        stmt = update(Run).where(Run.id == run_id)
        if claim_token is not None:
            stmt = stmt.where(Run.claim_token == claim_token)
        result = await db.execute(stmt.values(**values))
        await db.commit()
        return bool(result.rowcount)


async def _fetch_run(
    session_factory: async_sessionmaker,
    run_id: str,
) -> Run | None:
    async with session_factory() as db:
        result = await db.execute(select(Run).where(Run.id == run_id))
        return result.scalar_one_or_none()


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
                    select(JobRaw.job_url, JobRaw.title, JobRaw.description, JobRaw.embedding).where(JobRaw.job_url.in_(chunk_urls))
                )
                rows = result.all()
                if not rows:
                    processed += len(chunk_urls)
                    continue

                rows_by_url = {row.job_url: row for row in rows}
                ordered_rows = [rows_by_url[url] for url in chunk_urls if url in rows_by_url]
                pending_rows = [row for row in ordered_rows if row.embedding is None]
                already_embedded = len(ordered_rows) - len(pending_rows)
                processed += already_embedded
                if not pending_rows:
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
                    continue
                descriptions = [row.description or "" for row in pending_rows]
                raw_skills_list = extract_skills_from_texts(descriptions, cfg)
                chunk_specs: list[tuple[str, str, str]] = []
                for row, raw_skills in zip(pending_rows, raw_skills_list):
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

                processed += len(pending_rows)
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
                del rows, ordered_rows, pending_rows, rows_by_url, descriptions, raw_skills_list, chunk_specs
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


async def _check_run_stop_state(
    session_factory: async_sessionmaker,
    run_id: str,
    *,
    claim_token: str | None = None,
) -> str | None:
    run = await _fetch_run(session_factory, run_id)
    if not run:
        return "missing"
    if claim_token is not None and run.claim_token != claim_token:
        return "lost_claim"
    if run.status == "cancelled":
        return "cancelled"
    if run.cancel_requested:
        return "cancel_requested"
    return None

_queues: dict[str, asyncio.Queue] = {}


def get_queue(mode: str = "quick") -> asyncio.Queue:
    if mode not in _queues:
        _queues[mode] = asyncio.Queue(maxsize=100)
    return _queues[mode]


async def process_run(
    run_id: str, user_id: str, session_factory: async_sessionmaker,
    mode: str = "quick",
    force_scrape: bool = False,
    disable_scraping: bool = False,
    claim_token: str | None = None,
) -> None:
    async with session_factory() as db:
        scrape_executed = False
        scrape_reason = "pending"
        try:
            log_rss(logger, "run_start", run_id=run_id, user_id=user_id, mode=mode)
            run_check_result = await db.execute(select(Run).where(Run.id == run_id))
            run_check = run_check_result.scalar_one_or_none()
            if not run_check:
                logger.info("Run %s not found before starting, skipping", run_id)
                return
            if claim_token is not None and run_check.claim_token != claim_token:
                logger.info("Run %s claim token no longer owned, skipping", run_id)
                return
            if run_check.status == "cancelled" or run_check.cancel_requested:
                if run_check.cancel_requested and claim_token is not None:
                    await mark_run_cancelled(
                        _update_run_row,
                        session_factory,
                        run_id,
                        claim_token=claim_token,
                    )
                logger.info("Run %s not found or cancelled before starting, skipping", run_id)
                return

            initial_values = {
                "status": "scraping",
                "lease_expires_at": _lease_until(),
                "last_heartbeat_at": datetime.now(timezone.utc),
                "executor_type": "worker",
            }
            stmt = update(Run).where(Run.id == run_id)
            if claim_token is not None:
                stmt = stmt.where(Run.claim_token == claim_token)
            await db.execute(stmt.values(**initial_values))
            await db.commit()

            profile_result = await db.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = profile_result.scalar_one_or_none()
            auto_refresh = bool((run_check.progress or {}).get("auto_refresh", False))
            resume_text = profile.resume_text if profile else ""
            distilled_text = profile.distilled_text if profile else None
            config_overrides = profile.config_overrides if profile else None
            ctx = build_context(user_id=user_id, resume_text=resume_text, config_overrides=config_overrides)
            cfg = ctx.config
            async def _update_progress(**kwargs):
                await _update_run_row(
                    session_factory,
                    run_id,
                    claim_token=claim_token,
                    values={
                        "progress": merge_run_progress(
                            mode,
                            force_scrape,
                            disable_scraping,
                            auto_refresh=auto_refresh,
                            scrape_executed=scrape_executed,
                            scrape_reason=scrape_reason,
                            **kwargs,
                        ),
                        "last_heartbeat_at": datetime.now(timezone.utc),
                        "lease_expires_at": _lease_until(),
                    },
                )

            if mode == "quick":
                scraper_max_terms = 1
                scraper_hours_old = 24
            else:
                scraper_max_terms = profile.scraper_max_terms if profile else None
                scraper_hours_old = profile.scraper_hours_old or 168  # 7 days
            from batch.scraper import ScraperConfig
            scraper_cfg = ScraperConfig.from_env(title_blocklist=(config_overrides or {}).get("title_blocklist", []))
            scraper_cfg.hours_old = scraper_hours_old
            if mode == "quick":
                scraper_cfg.sources = ["indeed"]
            candidate_profile = build_candidate_profile(profile=profile, resume_text=resume_text, cfg=cfg) if profile else {}

            async def _progress_writer(**kwargs):
                await _update_run_row(
                    session_factory,
                    run_id,
                    claim_token=claim_token,
                    values={
                        "progress": merge_run_progress(
                            mode,
                            force_scrape,
                            disable_scraping,
                            auto_refresh=auto_refresh,
                            **kwargs,
                        ),
                        "last_heartbeat_at": datetime.now(timezone.utc),
                        "lease_expires_at": _lease_until(),
                    },
                )

            try:
                scrape_result = await execute_scrape_pipeline(
                    session_factory=session_factory,
                    db=db,
                    run_id=run_id,
                    user_id=user_id,
                    mode=mode,
                    force_scrape=force_scrape,
                    disable_scraping=disable_scraping,
                    auto_refresh=auto_refresh,
                    profile=profile,
                    resume_text=resume_text,
                    config_overrides=config_overrides,
                    candidate_profile=candidate_profile,
                    cfg=cfg,
                    scraper_cfg=scraper_cfg,
                    scraper_max_terms=scraper_max_terms or settings.scraper_max_terms,
                    scraper_hours_old=scraper_hours_old,
                    claim_token=claim_token,
                    progress_writer=_progress_writer,
                    check_run_stop_state=_check_run_stop_state,
                    embed_new_jobs=_embed_new_jobs,
                )
            except ScrapePipelineStopRequested as stop_exc:
                if stop_exc.state == "cancel_requested":
                    await mark_run_cancelled(
                        _update_run_row,
                        session_factory,
                        run_id,
                        claim_token=claim_token,
                    )
                logger.info("Run %s stopped during scraping (%s)", run_id, stop_exc.state)
                return

            scrape_executed = scrape_result.scrape_executed
            scrape_reason = scrape_result.scrape_reason
            scrape_count = scrape_result.scrape_count
            freshly_scraped_job_urls = scrape_result.freshly_scraped_job_urls
            rerank_corpus_meta: dict[str, str | int] | None = scrape_result.rerank_corpus_meta

            if disable_scraping and not freshly_scraped_job_urls:
                freshly_scraped_job_urls, rerank_corpus_meta = await load_rerank_corpus_job_urls(
                    db,
                    user_id=user_id,
                    mode=mode,
                    exclude_run_id=run_id,
                )
                if freshly_scraped_job_urls:
                    logger.info(
                        "Run %s rerank-only mode resolved %d jobs from %s",
                        run_id,
                        len(freshly_scraped_job_urls),
                        rerank_corpus_meta.get("corpus_source") if rerank_corpus_meta else "unknown",
                    )
                else:
                    rerank_corpus_meta = corpus_progress(
                        corpus_source="empty_existing_corpus",
                        corpus_job_count=0,
                    )
                    logger.info("Run %s rerank-only mode found no existing corpus to rescore", run_id)

            if rerank_corpus_meta is None and not freshly_scraped_job_urls:
                rerank_corpus_meta = corpus_progress(corpus_source="default_rank_scope")

            stop_state = await _check_run_stop_state(session_factory, run_id, claim_token=claim_token)
            if stop_state:
                if stop_state == "cancel_requested":
                    await mark_run_cancelled(
                        _update_run_row,
                        session_factory,
                        run_id,
                        claim_token=claim_token,
                    )
                logger.info("Run %s stopped before ranking (%s)", run_id, stop_state)
                return

            await _update_run_row(
                session_factory,
                run_id,
                claim_token=claim_token,
                values={
                    "status": "ranking",
                    "scrape_count": scrape_count,
                    "progress": merge_run_progress(
                        mode,
                        force_scrape,
                        disable_scraping,
                        auto_refresh=auto_refresh,
                        scrape_executed=scrape_executed,
                        scrape_reason=scrape_reason,
                        phase="ranking",
                        phase_num=1,
                        total_phases=1,
                        jobs_found=scrape_count,
                        rerank_corpus_jobs=len(freshly_scraped_job_urls or []),
                        **(rerank_corpus_meta or {}),
                        message="Ranking jobs...",
                    ),
                    "last_heartbeat_at": datetime.now(timezone.utc),
                    "lease_expires_at": _lease_until(),
                },
            )
            log_rss(logger, "before_rank", run_id=run_id, scrape_count=scrape_count)

            t_rank = time.monotonic()
            try:
                score_jobs_for_user = _get_score_jobs_for_user()
                logger.info("Using scorer version: v4", extra={"run_id": run_id})
                score_kwargs = dict(
                    db=db,
                    user_id=user_id,
                    resume_text=resume_text,
                    distilled_text=distilled_text,
                    config_overrides=config_overrides,
                    job_urls=freshly_scraped_job_urls,
                    preserve_corpus=disable_scraping,
                )
                ranked_df = await asyncio.wait_for(
                    score_jobs_for_user(**score_kwargs),
                    timeout=600,  # 10 min max
                )
            except asyncio.TimeoutError:
                logger.error("Run %s ranking timed out after 600s", run_id)
                await mark_run_failed(
                    _update_run_row,
                    session_factory,
                    run_id,
                    mode=mode,
                    force_scrape=force_scrape,
                    disable_scraping=disable_scraping,
                    error="TimeoutError: Ranking timed out after 600s",
                    claim_token=claim_token,
                    auto_refresh=auto_refresh,
                    scrape_executed=scrape_executed,
                    scrape_reason=scrape_reason,
                )
                raise
            logger.info("Run %s ranking done in %.1fs, %d jobs",
                        run_id, time.monotonic() - t_rank, len(ranked_df))
            log_rss(logger, "after_rank", run_id=run_id, ranked_jobs=len(ranked_df))

            stop_state = await _check_run_stop_state(session_factory, run_id, claim_token=claim_token)
            if stop_state:
                if stop_state == "cancel_requested":
                    await mark_run_cancelled(
                        _update_run_row,
                        session_factory,
                        run_id,
                        claim_token=claim_token,
                    )
                logger.info("Run %s stopped before saving results (%s)", run_id, stop_state)
                return

            ranked_df = normalize_ranked_df(ranked_df)
            await persist_ranked_results(
                db,
                ranked_df=ranked_df,
                run_id=run_id,
                user_id=user_id,
            )
            availability_archive_meta: dict[str, int] = {}
            if _should_archive_availability_after_run(len(ranked_df)):
                try:
                    t_archive = time.monotonic()
                    availability_result = await archive_expired_jobs_for_user(
                        db,
                        user_id=user_id,
                        run_id=run_id,
                        limit=settings.job_availability_archive_limit,
                    )
                    availability_archive_meta = {
                        "availability_checked": int(availability_result["checked"]),
                        "availability_expired": int(availability_result["expired"]),
                        "availability_unknown": int(availability_result["unknown"]),
                        "availability_archived": int(availability_result["archived"]),
                        "tracker_archived": int(availability_result["tracker_archived"]),
                    }
                    logger.info(
                        "Run %s availability archive checked %d jobs in %.1fs; archived %d",
                        run_id,
                        availability_archive_meta["availability_checked"],
                        time.monotonic() - t_archive,
                        availability_archive_meta["availability_archived"],
                    )
                except Exception:
                    logger.warning(
                        "Run %s availability archive failed; continuing",
                        run_id,
                        exc_info=True,
                    )
            release_memory(logger, "result_rows_release", run_id=run_id)

            await _update_run_row(
                session_factory,
                run_id,
                claim_token=claim_token,
                values={
                    "status": "success",
                    "finished_at": datetime.now(timezone.utc),
                    "job_count": len(ranked_df),
                    "progress": run_progress_meta(
                        mode,
                        force_scrape,
                        disable_scraping,
                        auto_refresh=auto_refresh,
                        scrape_executed=scrape_executed,
                        scrape_reason=scrape_reason,
                    )
                    | (rerank_corpus_meta or {})
                    | corpus_progress(
                        scored_job_count=len(ranked_df),
                        shown_job_count=len(ranked_df),
                    )
                    | availability_archive_meta
                    | (
                        {"rerank_corpus_jobs": len(freshly_scraped_job_urls or [])}
                        if disable_scraping
                        else {}
                    ),
                    "error": None,
                    "claim_token": None,
                    "claimed_by": None,
                    "lease_expires_at": None,
                    "last_heartbeat_at": datetime.now(timezone.utc),
                },
            )
            try:
                db.expire_all()
                from api.routes.jobs import warm_default_jobs_cache
                await warm_default_jobs_cache(db, user_id=user_id)
            except Exception:
                logger.debug("Skipping jobs cache warm-up after run completion", exc_info=True)
            logger.info("Run %s (%s) completed: %d scraped, %d ranked", run_id, mode, scrape_count, len(ranked_df))
            del ranked_df
            gc.collect()
            release_memory(logger, "after_rank_cleanup", run_id=run_id)
            clear_vector_cache()
            release_memory(logger, "run_complete_release", run_id=run_id, mode=mode)

        except _TRANSIENT_EXCEPTIONS as exc:
            logger.warning("Run %s transient failure", run_id, exc_info=True)
            try:
                await db.rollback()
                await mark_run_failed(
                    _update_run_row,
                    session_factory,
                    run_id,
                    mode=mode,
                    force_scrape=force_scrape,
                    disable_scraping=disable_scraping,
                    error=_format_run_error(exc),
                    claim_token=claim_token,
                    auto_refresh=auto_refresh,
                    scrape_executed=scrape_executed,
                    scrape_reason=scrape_reason,
                )
            except Exception:
                logger.warning("Run %s: failed to update status after transient error", run_id, exc_info=True)
            raise
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            try:
                await db.rollback()
                await mark_run_failed(
                    _update_run_row,
                    session_factory,
                    run_id,
                    mode=mode,
                    force_scrape=force_scrape,
                    disable_scraping=disable_scraping,
                    error=_format_run_error(exc),
                    claim_token=claim_token,
                    auto_refresh=auto_refresh,
                    scrape_executed=scrape_executed,
                    scrape_reason=scrape_reason,
                )
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
        now = datetime.now(timezone.utc)
        stale = await db.execute(
            select(Run).where(Run.status.in_(["claimed", "scraping", "ranking"]))
        )
        for run in stale.scalars().all():
            if run.lease_expires_at and run.lease_expires_at > now:
                continue
            run.status = "pending"
            run.claimed_by = None
            run.claim_token = None
            run.lease_expires_at = None
            run.last_heartbeat_at = None
            run.error = "Recovered stale run for retry"
            logger.warning("Re-queued stale run %s", run.id)
        await db.commit()


async def _claim_pending_run(session_factory: async_sessionmaker, mode: str, local_worker: bool = False) -> RunRequest | None:
    """Claim the oldest runnable run for the given mode using a short DB transaction."""
    async with session_factory() as db:
        now = datetime.now(timezone.utc)
        # DB-level guard: don't claim if a run of this mode is already active.
        active_count = await db.scalar(
            select(func.count(Run.id)).where(
                Run.status.in_(["claimed", "scraping", "ranking", "embedding", "running"]),
                Run.mode == mode,
                Run.lease_expires_at.is_not(None),
                Run.lease_expires_at > now,
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

        if local_worker:
            executor_filter = Run.executor_type == "local"
        elif os.environ.get("CLAIM_ALL_EXECUTOR_TYPES", "").lower() == "true":
            # Local dev: plain worker claims all runs regardless of executor_type
            executor_filter = or_(
                Run.executor_type.is_(None),
                Run.executor_type == "cloud",
                Run.executor_type == "local",
            )
        else:
            executor_filter = or_(
                Run.executor_type.is_(None),
                Run.executor_type == "cloud",
            )

        claimable_filter = and_(
            Run.mode == mode,
            executor_filter,
            or_(
                Run.status == "pending",
                and_(
                    Run.status.in_(["claimed", "scraping", "ranking"]),
                    or_(Run.lease_expires_at.is_(None), Run.lease_expires_at <= now),
                ),
            ),
        )
        candidate_rows = (
            select(
                Run.user_id.label("user_id"),
                func.min(Run.started_at).label("oldest_started_at"),
            )
            .where(claimable_filter)
            .group_by(Run.user_id)
            .order_by(func.min(Run.started_at).asc())
            .limit(32)
        )
        candidates = (await db.execute(candidate_rows)).all()
        if not candidates:
            await db.rollback()
            return None

        run = None
        for candidate in candidates:
            stmt = (
                select(Run)
                .where(
                    claimable_filter,
                    Run.user_id == candidate.user_id,
                )
                .order_by(Run.started_at.asc(), Run.id.asc())
                .limit(1)
            )
            if dialect_name(db) != "sqlite":
                stmt = stmt.with_for_update(skip_locked=True)
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run is not None:
                break

        if not run:
            await db.rollback()
            return None

        progress = run.progress if isinstance(run.progress, dict) else {}
        force_scrape = bool(progress.get("force_scrape", False))
        disable_scraping = bool(progress.get("disable_scraping", False))
        run.status = "claimed"
        run.claimed_by = _worker_identity()
        run.claim_token = uuid.uuid4().hex
        run.lease_expires_at = _lease_until(now)
        run.last_heartbeat_at = now
        run.attempt_count = (run.attempt_count or 0) + 1
        run.cancel_requested = False
        if not local_worker:
            run.executor_type = "worker"
        await db.commit()
        logger.info(
            "Claimed %s run %s from DB poll (user_id=%s force_scrape=%s disable_scraping=%s worker=%s)",
            mode, run.id, run.user_id, force_scrape, disable_scraping, run.claimed_by,
        )
        return RunRequest(str(run.id), str(run.user_id), mode, force_scrape, disable_scraping, run.claim_token)


async def _claim_run_by_id(session_factory: async_sessionmaker, req: RunRequest, local_worker: bool = False) -> RunRequest | None:
    async with session_factory() as db:
        now = datetime.now(timezone.utc)
        stmt = select(Run).where(Run.id == req.run_id, Run.mode == req.mode).limit(1)
        if dialect_name(db) != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            await db.rollback()
            return None
        if run.status not in {"pending", "claimed", "scraping", "ranking"}:
            await db.rollback()
            return None
        if run.status in {"claimed", "scraping", "ranking"} and run.lease_expires_at and run.lease_expires_at > now:
            await db.rollback()
            return None
        progress = run.progress if isinstance(run.progress, dict) else {}
        run.status = "claimed"
        run.claimed_by = _worker_identity()
        run.claim_token = uuid.uuid4().hex
        run.lease_expires_at = _lease_until(now)
        run.last_heartbeat_at = now
        run.attempt_count = (run.attempt_count or 0) + 1
        run.cancel_requested = False
        if not local_worker:
            run.executor_type = "worker"
        await db.commit()
        return RunRequest(
            str(run.id),
            str(run.user_id),
            run.mode,
            bool(progress.get("force_scrape", req.force_scrape)),
            bool(progress.get("disable_scraping", req.disable_scraping)),
            run.claim_token,
        )


async def _worker_loop_for_mode(session_factory: async_sessionmaker, mode: str, local_worker: bool = False) -> None:
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
            item = await _claim_pending_run(session_factory, mode, local_worker=local_worker)
            if item is None:
                continue

        if isinstance(item, RunRequest):
            req = item
        elif len(item) == 6:
            req = RunRequest(*item)
        elif len(item) == 5:
            req = RunRequest(*item)
        elif len(item) == 4:
            req = RunRequest(*item)
        elif len(item) == 3:
            req = RunRequest(item[0], item[1], item[2])
        else:
            req = RunRequest(item[0], item[1])

        if from_queue:
            logger.info(
                "Dequeued %s run %s from in-process queue (user_id=%s force_scrape=%s disable_scraping=%s)",
                mode, req.run_id, req.user_id, req.force_scrape, req.disable_scraping,
            )
            claimed_req = await _claim_run_by_id(session_factory, req, local_worker=local_worker)
            if claimed_req is None:
                logger.info("Run %s could not be claimed from queue; skipping", req.run_id)
                continue
            req = claimed_req
        try:
            for attempt in range(1, _RUN_MAX_RETRIES + 1):
                try:
                    await process_run(
                        req.run_id,
                        req.user_id,
                        session_factory,
                        mode=req.mode,
                        force_scrape=req.force_scrape,
                        disable_scraping=req.disable_scraping,
                        claim_token=req.claim_token,
                    )
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


async def worker_loop(session_factory: async_sessionmaker, local_worker: bool = False) -> None:
    """Start one worker loop per scan mode and run them concurrently."""
    await _cleanup_stale_runs(session_factory)
    logger.info("Background worker started")
    await asyncio.gather(
        _worker_loop_for_mode(session_factory, "quick", local_worker=local_worker),
        _worker_loop_for_mode(session_factory, "full", local_worker=local_worker),
    )
