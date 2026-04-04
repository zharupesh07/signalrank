import argparse
import asyncio
import gc
import logging
from datetime import datetime, timezone

from sqlalchemy import select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.database import AsyncSessionLocal
from api.models import JobRaw, Profile, User
from batch.context import build_context
from batch.query_plan_cache import get_cached_queries
from batch.ranker import score_job_ids_for_user
from batch.scraper import ScraperConfig, raw_job_to_dict, scrape
from domain.candidate_profile import build_candidate_profile
from domain.job_profile import build_job_profile
from domain.role_clusters import roles_to_clusters

logger = logging.getLogger(__name__)


async def _resolve_user(email: str | None, user_id: str | None) -> tuple[str, Profile]:
    async with AsyncSessionLocal() as db:
        if user_id:
            stmt = (
                select(User.id, Profile)
                .join(Profile, Profile.user_id == User.id)
                .where(User.id == user_id)
            )
        else:
            stmt = (
                select(User.id, Profile)
                .join(Profile, Profile.user_id == User.id)
                .where(User.email == email)
            )
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            raise RuntimeError("User/profile not found")
        return row[0], row[1]


async def _persist_raw_jobs(raw_jobs: list, role_clusters: list[str]) -> list[str]:
    if not raw_jobs:
        return []
    values = [raw_job_to_dict(job) for job in raw_jobs]
    cfg = build_context(user_id="__quick_rank__", resume_text="").config
    for value in values:
        value["role_clusters"] = role_clusters
        value["job_profile"] = build_job_profile(
            title=value.get("title"),
            company=value.get("company"),
            description=value.get("description"),
            location=value.get("location"),
            site=value.get("site"),
            date_posted=value.get("date_posted"),
            role_clusters=role_clusters,
            cfg=cfg,
        )

    async with AsyncSessionLocal() as db:
        stmt = (
            pg_insert(JobRaw).values(values)
                .on_conflict_do_update(
                    index_elements=["job_url"],
                    set_={
                        "title": pg_insert(JobRaw).excluded.title,
                        "company": pg_insert(JobRaw).excluded.company,
                        "description": pg_insert(JobRaw).excluded.description,
                        "location": pg_insert(JobRaw).excluded.location,
                        "site": pg_insert(JobRaw).excluded.site,
                        "date_posted": pg_insert(JobRaw).excluded.date_posted,
                        "role_clusters": sa_text(
                            "(SELECT jsonb_agg(DISTINCT elem) "
                            "FROM jsonb_array_elements("
                            "COALESCE(jobs_raw.role_clusters, '[]'::jsonb) || "
                            "excluded.role_clusters) AS elem)"
                        ),
                        "job_profile": pg_insert(JobRaw).excluded.job_profile,
                    },
                )
            )
        await db.execute(stmt)
        await db.commit()

        urls = [job.job_url for job in raw_jobs]
        result = await db.execute(select(JobRaw.id).where(JobRaw.job_url.in_(urls)))
        return [row[0] for row in result.all()]


async def _scrape_and_rank(email: str | None, user_id: str | None, limit: int) -> None:
    resolved_user_id, profile = await _resolve_user(email=email, user_id=user_id)
    resume_text = profile.resume_text or ""
    distilled_text = profile.distilled_text
    config_overrides = profile.config_overrides or {}
    ctx = build_context(resolved_user_id, resume_text, config_overrides)
    cfg = ctx.config
    candidate_profile = build_candidate_profile(profile=profile, resume_text=resume_text, cfg=cfg)

    title_blocklist = config_overrides.get("title_blocklist", [])
    scraper_cfg = ScraperConfig.from_env(title_blocklist=title_blocklist)
    scraper_cfg.hours_old = 24
    scraper_cfg.sources = ["indeed"]

    logger.info("Starting 24h scrape")
    started_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        queries = await get_cached_queries(
            db,
            profile=profile,
            profile_fingerprint=str(candidate_profile.get("profile_fingerprint") or candidate_profile.get("profile_cache_key") or ""),
            search_window_days=1,
            source_filter="indeed",
            max_terms=1,
        )
        raw_jobs = await scrape(queries, scraper_cfg, db=db)
    logger.info("Scrape complete: %d jobs", len(raw_jobs))

    role_clusters = sorted(roles_to_clusters(profile.target_roles or []))
    job_ids = await _persist_raw_jobs(raw_jobs, role_clusters)
    logger.info("Persisted/resolved %d job ids", len(job_ids))
    scraped_count = len(raw_jobs)
    del raw_jobs
    gc.collect()

    async with AsyncSessionLocal() as db:
        ranked_df = await score_job_ids_for_user(
            db=db,
            user_id=resolved_user_id,
            resume_text=resume_text,
            job_ids=job_ids,
            config_overrides=config_overrides,
            distilled_text=distilled_text,
        )

    print(
        {
            "user_id": resolved_user_id,
            "scraped_jobs": scraped_count,
            "ranked_jobs": len(ranked_df),
            "started_at": started_at.isoformat(),
        }
    )

    if ranked_df.empty:
        print("No ranked jobs produced")
        return

    cols = [
        "title",
        "company",
        "site",
        "final_score",
        "semantic_score",
        "skill_overlap",
        "role_skill_score",
        "company_tier",
        "strong_title_penalty",
        "adjacent_title",
        "hybrid_title",
    ]
    printable = ranked_df[cols].head(limit).copy()
    printable["final_score"] = printable["final_score"].round(2)
    printable["semantic_score"] = printable["semantic_score"].round(3)
    printable["role_skill_score"] = printable["role_skill_score"].round(3)
    print(printable.to_string(index=False))
    del ranked_df
    gc.collect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape 24h jobs and rank only the scraped set")
    parser.add_argument("--email", default="examplecandidate@gmail.com")
    parser.add_argument("--user-id")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_scrape_and_rank(email=args.email, user_id=args.user_id, limit=args.limit))


if __name__ == "__main__":
    main()
