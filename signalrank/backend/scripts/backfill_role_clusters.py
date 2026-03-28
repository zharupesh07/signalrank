"""
One-time backfill: tag existing jobs_raw rows with role_clusters based on
which users have job_results for them and what those users' target_roles are.

Jobs with no results at all are left as [] (visible to all users as "general").

Run: uv run python scripts/backfill_role_clusters.py
"""
import asyncio
import json
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.database import engine as db_engine
from api.models import Profile
from domain.role_clusters import roles_to_clusters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


async def run():
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with factory() as db:
        # user_id → sorted cluster list
        profiles = (await db.execute(select(Profile.user_id, Profile.target_roles))).all()
        user_clusters: dict[str, list[str]] = {
            str(uid): sorted(roles_to_clusters(roles or []) - {"general"})
            for uid, roles in profiles
        }
        logger.info("Loaded %d user profiles", len(user_clusters))

        # Build a VALUES table: (user_id, clusters_json) and join with job_results
        # to produce (job_id, merged_clusters) in one SQL statement, then bulk UPDATE.
        if not user_clusters:
            logger.info("No profiles — nothing to backfill")
            return

        # Build VALUES rows for the user→clusters mapping
        values_rows = ", ".join(
            f"('{uid}', '{json.dumps(clusters)}'::jsonb)"
            for uid, clusters in user_clusters.items()
        )

        # Single SQL: for each untagged job that has results, compute merged clusters
        merge_sql = text(f"""
            WITH user_map(user_id, clusters) AS (
                VALUES {values_rows}
            ),
            job_clusters AS (
                SELECT
                    jr.job_id,
                    jsonb_agg(DISTINCT elem) AS merged
                FROM job_results jr
                JOIN user_map um ON um.user_id::uuid = jr.user_id
                CROSS JOIN LATERAL jsonb_array_elements(um.clusters) AS elem
                WHERE jr.job_id IN (
                    SELECT id FROM jobs_raw
                    WHERE role_clusters IS NULL OR role_clusters = '[]'::jsonb
                )
                GROUP BY jr.job_id
            )
            UPDATE jobs_raw
            SET role_clusters = jc.merged
            FROM job_clusters jc
            WHERE jobs_raw.id = jc.job_id
        """)

        result = await db.execute(merge_sql)
        await db.commit()
        logger.info("Tagged %d jobs with role_clusters", result.rowcount)

        # Count remaining untagged (jobs with no results — left as [])
        remaining = (await db.execute(
            text("SELECT count(*) FROM jobs_raw WHERE role_clusters IS NULL OR role_clusters = '[]'::jsonb")
        )).scalar()
        logger.info("%d jobs have no results and remain as [] (visible to all users)", remaining)


if __name__ == "__main__":
    asyncio.run(run())
