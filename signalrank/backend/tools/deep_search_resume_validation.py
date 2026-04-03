from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.database import AsyncSessionLocal
from api.models import JobRaw, Profile, User
from batch.context import build_context
from batch.query_builder import build_queries
from batch.ranker import score_job_ids_for_user
from batch.scraper import ScraperConfig, raw_job_to_dict, scrape
from domain.candidate_profile import build_candidate_profile
from domain.career_intent import build_career_intent_profile
from domain.job_profile import build_job_profile
from domain.role_clusters import infer_clusters_from_job_text
from domain.role_clusters import roles_to_clusters
from domain.embeddings import build_resume_embedding_text
from llm.resume_parser import ResumeParseResult
from api.routes.onboarding import _extract_text_from_pdf


logger = logging.getLogger(__name__)

RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"


@dataclass(frozen=True)
class ResumeTarget:
    key: str
    pdf_name: str


TARGETS = {
    "aditya": ResumeTarget("aditya", "aditya.pdf"),
    "ayush": ResumeTarget("ayush", "ayush_resume_new.pdf"),
}


def _load_spec(target: ResumeTarget) -> dict:
    return json.loads((RESUMES_DIR / target.pdf_name).with_suffix(".json").read_text())


def _parse_from_spec(spec: dict) -> ResumeParseResult:
    skills: list[str] = []
    for group in spec.get("skills") or []:
        skills.extend([str(item).strip() for item in group.get("items", []) if str(item).strip()])
    recent_titles = [exp.get("title", "") for exp in (spec.get("experiences") or [])[:3] if exp.get("title")]
    education = [edu.get("degree", "") for edu in (spec.get("education") or []) if edu.get("degree")]
    return ResumeParseResult(
        skills=skills,
        years_of_experience=None,
        recent_titles=recent_titles,
        industries=[],
        education=education,
        suggested_roles=[str(spec.get("position") or spec.get("label") or "").strip()],
        suggested_locations=[str(spec.get("location") or "").split(",")[0].strip()] if spec.get("location") else [],
        suggested_exclusions=[],
        suggested_search_queries=[],
        career_archetypes=[],
        target_roles=[],
        domains=[],
        negative_targets=[],
        false_friend_terms=[],
        query_plan={},
        ambiguities=[],
        follow_up_questions=[],
    )


async def _persist_jobs(db, jobs, cfg):
    if not jobs:
        return []
    values = [raw_job_to_dict(job) for job in jobs]
    for value in values:
        value["role_clusters"] = sorted(
            infer_clusters_from_job_text(value.get("title"), value.get("description")) - {"general"}
        )
        value["job_profile"] = build_job_profile(
            title=value.get("title"),
            company=value.get("company"),
            description=value.get("description"),
            location=value.get("location"),
            site=value.get("site"),
            date_posted=value.get("date_posted"),
            role_clusters=value["role_clusters"],
            cfg=cfg,
        )
    stmt = pg_insert(JobRaw).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_url"],
        set_={
            "title": stmt.excluded.title,
            "company": stmt.excluded.company,
            "description": stmt.excluded.description,
            "location": stmt.excluded.location,
            "site": stmt.excluded.site,
            "date_posted": stmt.excluded.date_posted,
            "role_clusters": stmt.excluded.role_clusters,
            "job_profile": stmt.excluded.job_profile,
        },
    )
    await db.execute(stmt)
    await db.commit()

    urls = [job.job_url for job in jobs]
    result = await db.execute(select(JobRaw.id).where(JobRaw.job_url.in_(urls)))
    return [str(row[0]) for row in result.all()]


async def _run_target(target: ResumeTarget, days: int, limit: int, quick_search: bool) -> None:
    run_id = uuid.uuid4().hex[:10]
    spec = _load_spec(target)
    pdf_path = RESUMES_DIR / target.pdf_name
    resume_text = _extract_text_from_pdf(pdf_path.read_bytes())
    parsed = _parse_from_spec(spec)
    career_intent = build_career_intent_profile(parsed)

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"deep-search-{target.key}-{run_id}@test.com",
            password_hash="x",
            provider="credentials",
        )
        db.add(user)
        await db.flush()

        profile = Profile(
            user_id=user.id,
            resume_text=resume_text,
            target_roles=[r["title"] for r in career_intent.get("target_roles", []) if r.get("title")],
            preferred_locations=[loc for loc in career_intent.get("suggested_locations", []) if loc],
            onboarding_complete=True,
            scraper_max_terms=8,
            scraper_hours_old=days * 24,
            config_overrides={"career_intent": career_intent},
        )
        db.add(profile)
        await db.commit()

        ctx = build_context(user_id=user.id, resume_text=resume_text, config_overrides=profile.config_overrides)
        cfg = ctx.config
        if quick_search:
            cfg.setdefault("ranking", {}).setdefault("agentic_matching", {})["enabled"] = False
        candidate_profile = build_candidate_profile(
            parsed=parsed,
            profile=profile,
            resume_text=resume_text,
            cfg=cfg,
        )
        queries = build_queries(profile, max_terms=profile.scraper_max_terms)
        scraper_cfg = ScraperConfig.from_env(title_blocklist=(profile.config_overrides or {}).get("title_blocklist", []))
        scraper_cfg.hours_old = days * 24
        scraper_cfg.sources = ["indeed"] if quick_search else ["indeed", "linkedin", "rapidapi", "free_apis", "google_jobs"]

        logger.info("Deep search for %s using %d queries", target.key, len(queries))
        jobs = await scrape(queries, scraper_cfg, return_mode="jobs")
        job_ids = await _persist_jobs(db, jobs, cfg)
        del jobs
        gc.collect()

        ranked = await score_job_ids_for_user(
            db=db,
            user_id=user.id,
            resume_text=resume_text,
            job_ids=job_ids,
            config_overrides=profile.config_overrides,
            distilled_text=profile.distilled_text,
        )
        ranked = ranked.sort_values("final_score", ascending=False).head(limit).reset_index(drop=True)
        top_ids = [str(row["id"]) for _, row in ranked.iterrows()]
        job_rows = await db.execute(select(JobRaw).where(JobRaw.id.in_(top_ids)))
        job_map = {str(row.id): row for row in job_rows.scalars().all()}

        resume_skill_set = set(candidate_profile.get("must_have_skills") or [])
        if not resume_skill_set:
            resume_skill_set = set(parsed.skills or [])

        print(f"\n=== {target.key.upper()} ===")
        print(f"queries={len(queries)} scraped={len(job_ids)} top20={len(ranked)}")
        for idx, row in ranked.iterrows():
            job = job_map.get(str(row["id"]))
            job_profile = job.job_profile if job else {}
            required_skills = set(job_profile.get("required_skills") or [])
            jd_text = (job.description or "") if job else ""
            overlap = sorted(resume_skill_set & required_skills)
            print(
                {
                    "rank": idx + 1,
                    "title": row["title"],
                    "company": row["company"],
                    "final_score": round(float(row["final_score"]), 2),
                    "semantic_score": round(float(row["semantic_score"]), 3),
                    "title_relevance_score": round(float(row.get("title_relevance_score", 0.0)), 2),
                    "job_domain": job_profile.get("domain"),
                    "job_role_family": job_profile.get("role_family"),
                    "jd_required_skills": list(required_skills)[:8],
                    "resume_job_overlap": overlap[:8],
                    "jd_excerpt": jd_text[:220].replace("\n", " "),
                }
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Deep-search and validate top jobs for resume targets")
    parser.add_argument("--resume", action="append", choices=sorted(TARGETS.keys()), help="Target resume key", required=False)
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--quick-search", action="store_true", help="Use JobSpy Indeed only for a faster search")
    args = parser.parse_args()

    targets = args.resume or ["aditya", "ayush"]
    for key in targets:
        await _run_target(TARGETS[key], days=args.days, limit=args.limit, quick_search=args.quick_search)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
