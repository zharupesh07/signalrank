"""
One-time backfill: recompute jobs_raw.role_clusters from each job's own
title/description, not from the users who happened to scrape or rank it.

Run: uv run python scripts/backfill_role_clusters.py
"""
import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.database import engine as db_engine
from api.models import JobRaw
from domain.role_clusters import infer_clusters_from_job_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def run():
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with factory() as db:
        rows = (await db.execute(select(JobRaw.id, JobRaw.title, JobRaw.description))).all()
        logger.info("Loaded %d jobs", len(rows))

        updated = 0
        batch_size = 1000
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            for job_id, title, description in batch:
                clusters = sorted(infer_clusters_from_job_text(title, description) - {"general"})
                await db.execute(
                    update(JobRaw).where(JobRaw.id == job_id).values(role_clusters=clusters)
                )
                updated += 1
            await db.commit()
            logger.info("Updated %d/%d jobs", updated, len(rows))

        logger.info("Recomputed role_clusters for %d jobs", updated)


if __name__ == "__main__":
    asyncio.run(run())
