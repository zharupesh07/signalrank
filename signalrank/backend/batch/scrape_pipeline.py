from __future__ import annotations

import gc
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from batch import query_builder
from api.models import JobRaw, Profile, Run
from domain.job_profile import build_job_profile
from domain.role_clusters import infer_clusters_from_job_text

logger = logging.getLogger(__name__)


@dataclass
class ScrapePipelineResult:
    scrape_executed: bool
    scrape_reason: str
    scrape_count: int
    freshly_scraped_job_urls: list[str] | None
    rerank_corpus_meta: dict[str, str | int] | None


class ScrapePipelineStopRequested(RuntimeError):
    def __init__(self, state: str):
        super().__init__(state)
        self.state = state


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _normalize_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalize_text(value)).strip()


def _tokenize_text(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9\+#/.]+", _normalize_text(value))
        if len(token) >= 2
    }


def _phrase_match_score(title: str | None, phrases: list[str]) -> int:
    normalized_title = _normalize_key(title)
    score = 0
    for phrase in phrases:
        normalized_phrase = _normalize_key(phrase)
        if normalized_phrase and normalized_phrase in normalized_title:
            score += 1
    return score


def _location_signal(
    job_location: str, preferred_locations: list[str], preferred_modes: set[str]
) -> int:
    normalized_job_location = _normalize_key(job_location)
    if "remote" in normalized_job_location:
        return 2 if ("remote" in preferred_modes or not preferred_locations) else 1
    if not normalized_job_location or not preferred_locations:
        return 0
    for location in preferred_locations:
        normalized_location = _normalize_key(location)
        if not normalized_location:
            continue
        if (
            normalized_location in normalized_job_location
            or normalized_job_location in normalized_location
        ):
            return 1
    return 0


def select_fresh_jobs_for_embedding(
    rows: list[JobRaw],
    candidate_profile: dict | None,
) -> tuple[list[str], dict[str, int]]:
    if not rows:
        return [], {
            "input_count": 0,
            "selected_count": 0,
            "dropped_no_signal": 0,
            "dropped_duplicates": 0,
            "boosted_cluster": 0,
            "boosted_title": 0,
            "boosted_skill": 0,
        }

    profile = candidate_profile or {}
    target_roles = [
        str(role).strip()
        for role in [
            *(profile.get("target_roles_primary") or []),
            *(profile.get("target_roles_adjacent") or []),
        ]
        if str(role or "").strip()
    ]
    target_role_keys = {
        _normalize_key(role) for role in target_roles if _normalize_key(role)
    }
    target_role_tokens = _tokenize_text(" ".join(target_roles))
    negative_roles = {
        _normalize_key(role)
        for role in (profile.get("negative_roles") or [])
        if _normalize_key(role)
    }
    preferred_locations = [
        str(location).strip()
        for location in (profile.get("preferred_locations") or [])
        if str(location or "").strip()
    ]
    preferred_modes = {
        _normalize_key(mode)
        for mode in (profile.get("preferred_work_modes") or [])
        if _normalize_key(mode)
    }
    target_clusters = {
        str(cluster)
        for cluster in (profile.get("career_clusters") or [])
        if str(cluster or "").strip()
    }
    must_have_skills = {
        _normalize_key(skill)
        for skill in (profile.get("must_have_skills") or [])
        if _normalize_key(skill)
    }
    good_to_have_skills = {
        _normalize_key(skill)
        for skill in (profile.get("good_to_have_skills") or [])
        if _normalize_key(skill)
    }
    target_domains = {
        _normalize_key(domain)
        for domain in (profile.get("preferred_domains") or [])
        if _normalize_key(domain)
    }

    seen_fingerprints: dict[str, tuple[int, str]] = {}
    metrics = {
        "input_count": len(rows),
        "selected_count": 0,
        "dropped_no_signal": 0,
        "dropped_duplicates": 0,
        "boosted_cluster": 0,
        "boosted_title": 0,
        "boosted_skill": 0,
    }

    for row in rows:
        job_profile = row.job_profile if isinstance(row.job_profile, dict) else {}
        role_clusters = {
            str(cluster)
            for cluster in (row.role_clusters or [])
            if str(cluster or "").strip()
        }
        title = row.title or ""
        company = row.company or ""
        location = row.location or ""
        job_location = str(job_profile.get("location_normalized") or location or "")
        job_skills = {
            _normalize_key(skill)
            for skill in [
                *(job_profile.get("required_skills") or []),
                *(job_profile.get("preferred_skills") or []),
            ]
            if _normalize_key(skill)
        }
        red_flags = {
            str(flag)
            for flag in (job_profile.get("red_flags") or [])
            if str(flag or "").strip()
        }
        description_quality = float(job_profile.get("description_quality") or 0)
        role_titles = [
            str(item)
            for item in (job_profile.get("role_titles_normalized") or [])
            if str(item or "").strip()
        ]
        domain = _normalize_key(
            str(job_profile.get("domain") or job_profile.get("role_family") or "")
        )
        title_tokens = _tokenize_text(title)

        score = 0
        positive_signal = False

        if role_clusters.intersection(target_clusters):
            score += 4
            positive_signal = True
            metrics["boosted_cluster"] += 1

        title_hits = _phrase_match_score(title, target_roles)
        if title_hits:
            score += 3 + min(title_hits - 1, 2)
            positive_signal = True
            metrics["boosted_title"] += 1
        elif any(
            _normalize_key(role_title) in target_role_keys for role_title in role_titles
        ):
            score += 2
            positive_signal = True
            metrics["boosted_title"] += 1

        skill_overlap = len(job_skills.intersection(must_have_skills))
        if skill_overlap:
            score += 2 + min(skill_overlap, 2)
            positive_signal = True
            metrics["boosted_skill"] += 1
        elif job_skills.intersection(good_to_have_skills):
            score += 1
            positive_signal = True
            metrics["boosted_skill"] += 1

        score += _location_signal(job_location, preferred_locations, preferred_modes)

        if domain and domain in target_domains:
            score += 1
            positive_signal = True

        if description_quality >= 0.9:
            score += 1
        elif description_quality < 0.45:
            score -= 2

        if "empty_description" in red_flags or "very_short_description" in red_flags:
            score -= 3
        if "boilerplate_heavy" in red_flags and not positive_signal:
            score -= 1

        if any(negative in _normalize_key(title) for negative in negative_roles):
            score -= 4

        if not positive_signal and not title_tokens.intersection(target_role_tokens):
            score -= 1

        if score < 2:
            metrics["dropped_no_signal"] += 1
            continue

        dedupe_key = "||".join(
            [
                _normalize_key(company),
                _normalize_key(title),
                _normalize_key(job_location),
            ]
        )
        existing = seen_fingerprints.get(dedupe_key)
        if existing is not None:
            metrics["dropped_duplicates"] += 1
            if score > existing[0]:
                seen_fingerprints[dedupe_key] = (score, row.job_url)
            continue
        seen_fingerprints[dedupe_key] = (score, row.job_url)

    selected = [
        job_url
        for _, job_url in sorted(
            seen_fingerprints.values(), key=lambda item: (-item[0], item[1])
        )
    ]
    if not selected:
        selected = [row.job_url for row in rows]
    metrics["selected_count"] = len(selected)
    return selected, metrics


async def _should_skip_scrape(
    db: AsyncSession,
    *,
    user_id: str,
    run_id: str,
    mode: str,
    force_scrape: bool,
    disable_scraping: bool,
    auto_refresh: bool,
) -> tuple[bool, str, int | None]:
    now = datetime.now(timezone.utc)
    skip_scrape = disable_scraping
    scrape_reason = "forced" if force_scrape else "manual_default"
    scrape_threshold_hours: int | None = None
    if disable_scraping:
        return True, "disabled", None

    if auto_refresh and not force_scrape:
        if mode == "full":
            deep_scan_cutoff = now - timedelta(hours=48)
            recent_runs_result = await db.execute(
                select(Run)
                .where(
                    Run.user_id == user_id,
                    Run.status == "success",
                    Run.finished_at >= deep_scan_cutoff,
                    Run.id != run_id,
                )
                .order_by(Run.finished_at.desc())
                .limit(20)
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
                select(Run.id)
                .where(
                    Run.user_id == user_id,
                    Run.status == "success",
                    Run.scrape_count.is_not(None),
                    Run.finished_at >= scrape_cutoff,
                    Run.id != run_id,
                )
                .limit(1)
            )
            skip_scrape = recent_scrape.scalar_one_or_none() is not None
        if skip_scrape:
            scrape_reason = "recent_auto_refresh"
    return skip_scrape, scrape_reason, scrape_threshold_hours


async def execute_scrape_pipeline(
    *,
    session_factory: async_sessionmaker,
    db: AsyncSession,
    run_id: str,
    user_id: str,
    mode: str,
    force_scrape: bool,
    disable_scraping: bool,
    auto_refresh: bool,
    profile: Profile | None,
    resume_text: str,
    config_overrides: dict | None,
    candidate_profile: dict | None,
    cfg,
    scraper_cfg,
    scraper_max_terms: int,
    scraper_hours_old: int,
    claim_token: str | None,
    progress_writer: Callable[..., Awaitable[None]],
    check_run_stop_state: Callable[..., Awaitable[str | None]],
    embed_new_jobs: Callable[..., Awaitable[None]],
) -> ScrapePipelineResult:
    from batch import scraper as scraper_mod
    from batch.query_plan_cache import get_cached_queries

    if profile:
        profile_fingerprint = str(
            (candidate_profile or {}).get("profile_fingerprint")
            or (candidate_profile or {}).get("profile_cache_key")
            or ""
        )
        queries = await get_cached_queries(
            db,
            profile=profile,
            profile_fingerprint=profile_fingerprint,
            search_window_days=max(1, scraper_hours_old // 24),
            source_filter=",".join(sorted(scraper_cfg.sources or [])),
            max_terms=scraper_max_terms,
        )
    else:
        queries = []

    query_plan_shadow = (
        query_builder.build_query_plan_debug(
            profile,
            max_terms=scraper_max_terms,
        )
        if profile
        else None
    )
    if query_plan_shadow:
        shadow_counts = query_plan_shadow.get("counts") or {}
        logger.info(
            "Run %s query plan stats: executed_terms=%d shadow_terms=%d rejected_candidates=%d risk_flags=%s",
            run_id,
            len({query.term for query in queries}),
            int(shadow_counts.get("intent_terms") or 0),
            int(shadow_counts.get("rejected_candidates") or 0),
            ",".join(query_plan_shadow.get("risk_flags") or []),
        )
        await progress_writer(
            query_plan={
                "executed_terms": len({query.term for query in queries}),
                "shadow_terms": int(shadow_counts.get("intent_terms") or 0),
                "rejected_candidates": int(
                    shadow_counts.get("rejected_candidates") or 0
                ),
                "risk_flags": query_plan_shadow.get("risk_flags") or [],
            }
        )

    skip_scrape, scrape_reason, scrape_threshold_hours = await _should_skip_scrape(
        db,
        user_id=user_id,
        run_id=run_id,
        mode=mode,
        force_scrape=force_scrape,
        disable_scraping=disable_scraping,
        auto_refresh=auto_refresh,
    )

    if skip_scrape:
        logger.info(
            "Run %s skipping scrape%s",
            run_id,
            (
                ""
                if disable_scraping
                else f" - recent scrape within {scrape_threshold_hours}h threshold"
            ),
        )

    scrape_count = 0
    freshly_scraped_job_urls: list[str] | None = None
    rerank_corpus_meta: dict[str, str | int] | None = None
    scrape_executed = False
    if queries and not skip_scrape:
        scrape_executed = True
        scrape_reason = "executed"
        scrape_queries = list(queries)
        cached_query_job_urls: list[str] = []

        async def _update_progress(**kwargs):
            await progress_writer(
                scrape_executed=True,
                scrape_reason=scrape_reason,
                **kwargs,
            )

        scrape_queries, cached_query_job_urls = (
            await scraper_mod.plan_incremental_scrape(
                scrape_queries,
                scraper_cfg,
                db,
            )
        )
        if cached_query_job_urls:
            logger.info(
                "Run %s incremental scrape reused %d cached job URLs across fresh queries",
                run_id,
                len(cached_query_job_urls),
            )
        if queries and not scrape_queries:
            logger.info(
                "Run %s incremental scrape found all queries fresh; skipping network fetch",
                run_id,
            )

        stop_state = await check_run_stop_state(
            session_factory, run_id, claim_token=claim_token
        )
        if stop_state:
            raise ScrapePipelineStopRequested(stop_state)

        async def _persist_jobs(jobs):
            jobs = [j for j in jobs if j.title and len(j.description or "") >= 20]
            if not jobs:
                return
            async with session_factory() as pdb:
                batch_size = 2000
                for i in range(0, len(jobs), batch_size):
                    batch = jobs[i : i + batch_size]
                    values = [scraper_mod.raw_job_to_dict(job) for job in batch]
                    for v in values:
                        v["role_clusters"] = sorted(
                            infer_clusters_from_job_text(
                                v.get("title"), v.get("description")
                            )
                            - {"general"}
                        )
                        v["job_profile"] = build_job_profile(
                            title=v.get("title"),
                            company=v.get("company"),
                            description=v.get("description"),
                            location=v.get("location"),
                            site=v.get("site"),
                            date_posted=v.get("date_posted"),
                            role_clusters=v["role_clusters"],
                            cfg=cfg,
                        )
                    insert_stmt = pg_insert(JobRaw).values(values)
                    stmt = insert_stmt.on_conflict_do_update(
                        index_elements=["job_url"],
                        set_={
                            "title": insert_stmt.excluded.title,
                            "company": insert_stmt.excluded.company,
                            "description": insert_stmt.excluded.description,
                            "location": insert_stmt.excluded.location,
                            "site": insert_stmt.excluded.site,
                            "date_posted": insert_stmt.excluded.date_posted,
                            "availability_urls": insert_stmt.excluded.availability_urls,
                            "role_clusters": insert_stmt.excluded.role_clusters,
                            "job_profile": insert_stmt.excluded.job_profile,
                            "ingested_at": insert_stmt.excluded.ingested_at,
                        },
                    )
                    await pdb.execute(stmt)
                await pdb.commit()

        scraped_job_urls: list[str] = []
        if scrape_queries:
            t_scrape = time.monotonic()
            scraped_job_urls = await scraper_mod.scrape(
                scrape_queries,
                scraper_cfg,
                on_progress=_update_progress,
                on_persist=_persist_jobs,
                db=db,
                return_mode="urls",
            )
            logger.info(
                "Run %s scrape done",
                run_id,
                extra={
                    "run_id": run_id,
                    "phase": "scrape",
                    "duration_s": round(time.monotonic() - t_scrape, 1),
                    "jobs_found": len(scraped_job_urls),
                },
            )
        else:
            logger.info("Run %s scrape no queries after cache reuse", run_id)

        stop_state = await check_run_stop_state(
            session_factory, run_id, claim_token=claim_token
        )
        if stop_state:
            raise ScrapePipelineStopRequested(stop_state)

        scrape_count = len(scraped_job_urls)
        combined_job_urls: list[str] = []
        seen_combined_job_urls: set[str] = set()
        for url in [*cached_query_job_urls, *scraped_job_urls]:
            if url and url not in seen_combined_job_urls:
                seen_combined_job_urls.add(url)
                combined_job_urls.append(url)

        freshly_scraped_job_urls = combined_job_urls if combined_job_urls else None
        if freshly_scraped_job_urls:
            rerank_corpus_meta = {
                "corpus_source": "fresh_scrape",
                "corpus_job_count": len(freshly_scraped_job_urls),
            }
            fresh_jobs_result = await db.execute(
                select(JobRaw).where(JobRaw.job_url.in_(freshly_scraped_job_urls))
            )
            fresh_jobs = fresh_jobs_result.scalars().all()
            selected_job_urls, selection_metrics = select_fresh_jobs_for_embedding(
                fresh_jobs,
                candidate_profile if profile else None,
            )
            freshly_scraped_job_urls = selected_job_urls or freshly_scraped_job_urls
            logger.info(
                "Run %s pre-embed selection kept %d/%d fresh jobs (%d no-signal, %d duplicates)",
                run_id,
                selection_metrics["selected_count"],
                selection_metrics["input_count"],
                selection_metrics["dropped_no_signal"],
                selection_metrics["dropped_duplicates"],
            )
            await _update_progress(
                phase="scraping",
                phase_num=0,
                total_phases=1,
                jobs_found=scrape_count,
                reused_jobs=len(cached_query_job_urls),
                selected_jobs=len(freshly_scraped_job_urls),
                message=f"Selected {len(freshly_scraped_job_urls)}/{scrape_count} fresh jobs for embedding",
            )
            logger.info(
                "Run %s will rank against %d freshly scraped job URLs (filtered mode)",
                run_id,
                len(freshly_scraped_job_urls),
            )

        if freshly_scraped_job_urls:
            t_embed = time.monotonic()
            await embed_new_jobs(
                db, freshly_scraped_job_urls, update_progress=_update_progress
            )
            logger.info(
                "Run %s embed done",
                run_id,
                extra={
                    "run_id": run_id,
                    "phase": "embed",
                    "duration_s": round(time.monotonic() - t_embed, 1),
                    "jobs": len(freshly_scraped_job_urls),
                },
            )
            gc.collect()

    return ScrapePipelineResult(
        scrape_executed=scrape_executed,
        scrape_reason=scrape_reason,
        scrape_count=scrape_count,
        freshly_scraped_job_urls=freshly_scraped_job_urls,
        rerank_corpus_meta=rerank_corpus_meta,
    )
