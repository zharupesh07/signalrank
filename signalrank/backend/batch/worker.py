import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobResult, Profile, Run
from batch.ranker import score_jobs_for_user

logger = logging.getLogger(__name__)

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
            await db.execute(
                update(Run).where(Run.id == run_id).values(status="running")
            )
            await db.commit()

            profile_result = await db.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = profile_result.scalar_one_or_none()
            resume_text = profile.resume_text if profile else ""
            distilled_text = profile.distilled_text if profile else None
            config_overrides = profile.config_overrides if profile else None

            ranked_df = await score_jobs_for_user(
                db=db,
                user_id=user_id,
                resume_text=resume_text,
                distilled_text=distilled_text,
                config_overrides=config_overrides,
            )

            for _, row in ranked_df.iterrows():
                db.add(JobResult(
                    run_id=run_id,
                    user_id=user_id,
                    job_id=row["id"],
                    semantic_score=float(row.get("semantic_score", 0)),
                    skills_score=float(row.get("skills_score", 0)),
                    company_score=float(row.get("company_score", 0)),
                    seniority_score=float(row.get("seniority_score_dim", 0)),
                    location_score=float(row.get("location_score", 0)),
                    recency_score=float(row.get("recency_score", 0)),
                    final_score=float(row.get("final_score", 0)),
                    company_tier=str(row.get("company_tier", "")),
                    is_contract=bool(row.get("is_contract", False)),
                ))

            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="success",
                    finished_at=datetime.now(timezone.utc),
                    job_count=len(ranked_df),
                )
            )
            await db.commit()
            logger.info("Run %s completed: %d results", run_id, len(ranked_df))

        except Exception:
            logger.exception("Run %s failed", run_id)
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="failed", finished_at=datetime.now(timezone.utc))
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
