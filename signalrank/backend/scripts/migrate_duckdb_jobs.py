"""Migrate jobs from the legacy job_ranker DuckDB into SignalRank PostgreSQL,
then trigger a ranking run for the specified user.

Usage (dry-run, no writes):
    python -m scripts.migrate_duckdb_jobs --duckdb-path /path/to/duckdb --user-email examplecandidate@gmail.com --dry-run

Usage (live):
    python -m scripts.migrate_duckdb_jobs --duckdb-path /path/to/duckdb --user-email examplecandidate@gmail.com
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure extraction helpers — no DB, fully testable
# ---------------------------------------------------------------------------

def read_duckdb_jobs(
    duckdb_path: str,
    duck_user: str = "example",
    max_age_days: int = 30,
) -> list[dict]:
    """Read jobs from DuckDB for the given user posted within max_age_days."""
    import duckdb

    con = duckdb.connect(duckdb_path, read_only=True)
    rows = con.execute(
        """
        SELECT job_url, title, company, description, location, site,
               date_posted, ingested_at
        FROM   jobs_raw
        WHERE  "user" = ?
          AND  description IS NOT NULL
          AND  length(description) >= 20
          AND  date_posted >= NOW() - INTERVAL (? || ' days')
        ORDER BY ingested_at DESC
        """,
        [duck_user, str(max_age_days)],
    ).fetchall()
    con.close()

    cols = ["job_url", "title", "company", "description", "location",
            "site", "date_posted", "ingested_at"]
    return [dict(zip(cols, row)) for row in rows]


def clean_jobs(rows: list[dict]) -> list[dict]:
    """Normalise and sanitise rows before insertion."""
    out = []
    for r in rows:
        job_url = (r.get("job_url") or "").strip()
        if not job_url:
            continue

        date_posted = r.get("date_posted")
        if isinstance(date_posted, datetime):
            # Reject clearly bogus dates (before 2000)
            if date_posted.year < 2000:
                date_posted = None
            elif date_posted.tzinfo is None:
                date_posted = date_posted.replace(tzinfo=timezone.utc)

        ingested_at = r.get("ingested_at")
        if isinstance(ingested_at, datetime) and ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=timezone.utc)

        out.append({
            "job_url":     job_url,
            "title":       (r.get("title") or "").strip() or None,
            "company":     (r.get("company") or "").strip() or None,
            "description": r.get("description"),
            "location":    (r.get("location") or "").strip() or None,
            "site":        (r.get("site") or "").strip() or None,
            "date_posted": date_posted,
            "ingested_at": ingested_at or datetime.now(timezone.utc),
        })
    return out


def validate_jobs(jobs: list[dict]) -> list[str]:
    """Return a list of validation error strings (empty = all good)."""
    errors = []
    urls = set()
    for i, j in enumerate(jobs):
        if not j.get("job_url"):
            errors.append(f"Row {i}: missing job_url")
        if j["job_url"] in urls:
            errors.append(f"Row {i}: duplicate job_url {j['job_url']}")
        urls.add(j["job_url"])
        if not j.get("description") or len(j["description"]) < 20:
            errors.append(f"Row {i}: description too short for {j['job_url']}")
    return errors


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

async def insert_jobs_pg(jobs: list[dict], dry_run: bool = False) -> int:
    """Batch-insert jobs into PostgreSQL jobs_raw. Returns count inserted."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from api.database import AsyncSessionLocal
    from api.models import JobRaw

    if dry_run:
        logger.info("[DRY-RUN] Would insert %d jobs", len(jobs))
        return 0

    BATCH = 500
    total_inserted = 0
    async with AsyncSessionLocal() as db:
        for start in range(0, len(jobs), BATCH):
            batch = jobs[start : start + BATCH]
            stmt = (
                pg_insert(JobRaw)
                .values(batch)
                .on_conflict_do_nothing(index_elements=["job_url"])
            )
            result = await db.execute(stmt)
            total_inserted += result.rowcount
            await db.commit()
            logger.info("Inserted batch %d-%d (%d new)", start, start + len(batch), result.rowcount)

    return total_inserted


async def trigger_ranking_run(user_email: str, dry_run: bool = False) -> str | None:
    """Create a run record and rank all jobs for the user. Returns run_id."""
    from sqlalchemy import select
    from api.database import AsyncSessionLocal
    from api.models import Profile, Run, JobResult, User
    from ranking.v4.db_scorer import score_jobs_for_user

    if dry_run:
        logger.info("[DRY-RUN] Would trigger ranking for %s", user_email)
        return None

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(select(User).where(User.email == user_email))
        user = user_result.scalar_one_or_none()
        if not user:
            raise ValueError(f"User not found: {user_email}")

        profile_result = await db.execute(
            select(Profile).where(Profile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile or not profile.resume_text:
            raise ValueError(f"No resume found for {user_email}")

        run = Run(user_id=user.id, status="ranking")
        db.add(run)
        await db.flush()
        run_id = run.id
        await db.commit()

        logger.info("Created run %s, starting ranking...", run_id)

        ranked_df = await score_jobs_for_user(
            db=db,
            user_id=user.id,
            resume_text=profile.resume_text,
            distilled_text=profile.distilled_text,
            config_overrides=profile.config_overrides,
        )

        for _, row in ranked_df.iterrows():
            db.add(JobResult(
                run_id=run_id,
                user_id=user.id,
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

        from sqlalchemy import update
        await db.execute(
            update(Run).where(Run.id == run_id).values(
                status="success",
                finished_at=datetime.now(timezone.utc),
                job_count=len(ranked_df),
            )
        )
        await db.commit()
        logger.info("Run %s complete: %d jobs ranked", run_id, len(ranked_df))
        return run_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main(duckdb_path: str, user_email: str, dry_run: bool, max_age_days: int = 30) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    logger.info("Reading jobs from %s (max age: %d days)...", duckdb_path, max_age_days)
    raw = read_duckdb_jobs(duckdb_path, max_age_days=max_age_days)
    logger.info("Read %d jobs (with valid descriptions)", len(raw))

    jobs = clean_jobs(raw)
    logger.info("After cleaning: %d jobs", len(jobs))

    errors = validate_jobs(jobs)
    if errors:
        for e in errors[:10]:
            logger.error(e)
        if len(errors) > 10:
            logger.error("... and %d more errors", len(errors) - 10)
        sys.exit(1)

    logger.info("Validation passed.")

    if dry_run:
        logger.info("[DRY-RUN] Sample jobs:")
        for j in jobs[:3]:
            logger.info("  %s | %s | %s", j["job_url"], j["title"], j["company"])
        logger.info("[DRY-RUN] No writes performed.")
        return

    inserted = await insert_jobs_pg(jobs, dry_run=False)
    logger.info("Inserted %d new jobs into PostgreSQL (%d already existed)", inserted, len(jobs) - inserted)

    run_id = await trigger_ranking_run(user_email, dry_run=False)
    logger.info("Ranking run complete: %s", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate DuckDB jobs → SignalRank PG + rerank")
    parser.add_argument("--duckdb-path", required=True)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no DB writes")
    parser.add_argument("--max-age-days", type=int, default=30, help="Only import jobs posted within this many days (default: 30)")
    args = parser.parse_args()
    asyncio.run(main(args.duckdb_path, args.user_email, args.dry_run, args.max_age_days))
