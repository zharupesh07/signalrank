from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import (
    ArchivalQueue,
    GenerationQueue,
    JobResult,
    RecruiterRefreshTask,
    Run,
    ScrapeQueryCache,
    TailoredResume,
)

logger = logging.getLogger(__name__)

MAINTENANCE_LOCK_KEY = 1_947_017_470

DEFAULT_RETENTION_DAYS = 60
DEFAULT_CACHE_TTL_DAYS = 30
DEFAULT_SCRAPE_CACHE_TTL_DAYS = 14
DEFAULT_TASK_TTL_DAYS = 7
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class MaintenanceSummary:
    deleted: dict[str, int]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _delete_in_batches(session: AsyncSession, stmt_factory, *, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    total_deleted = 0
    while True:
        stmt = stmt_factory(limit=batch_size)
        result = await session.execute(stmt)
        batch_count = result.rowcount or 0
        total_deleted += batch_count
        if batch_count < batch_size:
            break
        await session.commit()
    return total_deleted


async def prune_scrape_query_cache(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or _now()) - timedelta(days=DEFAULT_SCRAPE_CACHE_TTL_DAYS)
    result = await db.execute(
        delete(ScrapeQueryCache).where(ScrapeQueryCache.fresh_until < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def prune_llm_cache(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or _now()) - timedelta(days=DEFAULT_CACHE_TTL_DAYS)
    result = await db.execute(
        text("DELETE FROM llm_cache WHERE created_at < :cutoff"),
        {"cutoff": cutoff},
    )
    await db.commit()
    return result.rowcount or 0


async def prune_recruiter_refresh_tasks(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or _now()) - timedelta(days=DEFAULT_TASK_TTL_DAYS)
    result = await db.execute(
        delete(RecruiterRefreshTask).where(
            RecruiterRefreshTask.finished_at.is_not(None),
            RecruiterRefreshTask.finished_at < cutoff,
        )
    )
    await db.commit()
    return result.rowcount or 0


async def prune_terminal_queues(db: AsyncSession) -> dict[str, int]:
    gen_deleted = (
        await db.execute(
            delete(GenerationQueue).where(GenerationQueue.status.in_(["done", "failed", "cancelled"]))
        )
    ).rowcount or 0
    arch_deleted = (
        await db.execute(
            delete(ArchivalQueue).where(ArchivalQueue.status.in_(["done", "failed", "cancelled"]))
        )
    ).rowcount or 0
    await db.commit()
    return {"generation_queue": gen_deleted, "archival_queue": arch_deleted}


async def prune_completed_runs_and_results(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    cutoff = (now or _now()) - timedelta(days=DEFAULT_RETENTION_DAYS)
    result = await db.execute(
        select(Run.id).where(
            Run.status.in_(["success", "failed", "cancelled"]),
            Run.finished_at.is_not(None),
            Run.finished_at < cutoff,
        )
    )
    run_ids = [str(row[0]) for row in result.all()]
    if not run_ids:
        return {"runs": 0, "job_results": 0, "tailored_resumes": 0}

    job_ids_result = await db.execute(
        select(JobResult.job_id).where(JobResult.run_id.in_(run_ids))
    )
    job_ids = [str(row[0]) for row in job_ids_result.all()]
    tailored_deleted = 0
    if job_ids:
        tailored_deleted = (
            await db.execute(
                delete(TailoredResume).where(TailoredResume.job_id.in_(job_ids))
            )
        ).rowcount or 0

    job_results_deleted = (
        await db.execute(delete(JobResult).where(JobResult.run_id.in_(run_ids)))
    ).rowcount or 0
    runs_deleted = (await db.execute(delete(Run).where(Run.id.in_(run_ids)))).rowcount or 0
    await db.commit()
    return {
        "runs": runs_deleted,
        "job_results": job_results_deleted,
        "tailored_resumes": tailored_deleted,
    }


async def prune_once(session_factory: async_sessionmaker, *, now: datetime | None = None) -> MaintenanceSummary:
    async with session_factory() as db:
        got_lock = await db.scalar(select(func.pg_try_advisory_lock(MAINTENANCE_LOCK_KEY)))
        if not got_lock:
            return MaintenanceSummary(deleted={})
        try:
            deleted: dict[str, int] = {}
            deleted["scrape_query_cache"] = await prune_scrape_query_cache(db, now=now)
            deleted["llm_cache"] = await prune_llm_cache(db, now=now)
            deleted["terminal_queues"] = sum((await prune_terminal_queues(db)).values())
            completed = await prune_completed_runs_and_results(db, now=now)
            deleted.update(completed)
            deleted["recruiter_refresh_tasks"] = await prune_recruiter_refresh_tasks(db, now=now)
            logger.info("Maintenance prune complete: %s", deleted)
            return MaintenanceSummary(deleted=deleted)
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": MAINTENANCE_LOCK_KEY})
            await db.commit()


async def maintenance_loop(session_factory: async_sessionmaker, *, interval_seconds: int = 3600) -> None:
    while True:
        try:
            await prune_once(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Maintenance prune failed; retrying later")
        await asyncio.sleep(interval_seconds)
