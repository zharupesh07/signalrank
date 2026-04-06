"""Local worker orchestrator.

Bridges Railway (run queue + user profiles) and local DB (scraping + ranking).

Flow for each run:
  1. Poll Railway for pending executor_type='local' runs
  2. Mirror User + Profile from Railway -> local DB
  3. Mirror Run from Railway -> local DB
  4. Call process_run() against local DB (scrape -> embed -> rank)
  5. Update Railway run status: syncing
  6. Call sync_results_to_railway() to push top-100 results
  7. Update Railway run status: completed
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import Profile, Run, User
from batch.local_sync import sync_results_to_railway
from batch.worker import RunRequest, _claim_pending_run, process_run

logger = logging.getLogger(__name__)

_SYNC_TOP_K = 100


async def mirror_user_and_profile(
    railway_db: AsyncSession,
    local_db: AsyncSession,
    user_id: str,
) -> None:
    """Copy User + Profile from railway_db to local_db (upsert)."""
    user = (await railway_db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise RuntimeError(f"User {user_id} not found in Railway DB")

    await local_db.execute(
        pg_insert(User)
        .values(
            id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            is_admin=getattr(user, "is_admin", False),
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={"email": pg_insert(User).excluded.email},
        )
    )

    profile = (
        await railway_db.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if not profile:
        raise RuntimeError(f"Profile for user {user_id} not found in Railway DB")

    profile_values: dict = {
        "id": profile.id,
        "user_id": profile.user_id,
        "resume_text": profile.resume_text,
        "onboarding_complete": profile.onboarding_complete,
    }
    for field in (
        "distilled_text",
        "config_overrides",
        "candidate_profile",
        "skills",
        "target_roles",
        "preferred_locations",
        "role_intent",
        "custom_search_queries",
        "scraper_hours_old",
        "scraper_max_terms",
    ):
        val = getattr(profile, field, None)
        if val is not None:
            profile_values[field] = val

    await local_db.execute(
        pg_insert(Profile)
        .values(**profile_values)
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "resume_text": pg_insert(Profile).excluded.resume_text,
                "config_overrides": pg_insert(Profile).excluded.config_overrides,
                "onboarding_complete": pg_insert(Profile).excluded.onboarding_complete,
            },
        )
    )
    await local_db.commit()
    logger.debug("Mirrored user+profile %s to local DB", user_id)


async def _mirror_run(
    railway_db: AsyncSession,
    local_db: AsyncSession,
    run_id: str,
    user_id: str,
    mode: str,
) -> None:
    """Copy Run row from Railway -> local DB."""
    run = (await railway_db.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        progress = {"requested_mode": mode, "force_scrape": False, "disable_scraping": False}
        run_values: dict = dict(
            id=run_id,
            user_id=user_id,
            status="claimed",
            mode=mode,
            executor_type="local",
            progress=progress,
        )
    else:
        run_values = dict(
            id=run.id,
            user_id=run.user_id,
            status=run.status,
            mode=run.mode,
            executor_type=run.executor_type,
            progress=run.progress,
            claim_token=run.claim_token,
            claimed_by=run.claimed_by,
        )
    _ins = pg_insert(Run).values(**run_values)
    await local_db.execute(
        _ins.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": _ins.excluded.status,
                "progress": _ins.excluded.progress,
                "claim_token": _ins.excluded.claim_token,
                "claimed_by": _ins.excluded.claimed_by,
            },
        )
    )
    await local_db.commit()


async def create_run_in_railway(
    railway_db: AsyncSession,
    user_id: str,
    mode: str = "quick",
) -> str:
    """Insert a pending executor_type='local' run in Railway and return its ID."""
    run_id = str(uuid.uuid4())
    railway_db.add(
        Run(
            id=run_id,
            user_id=user_id,
            status="pending",
            mode=mode,
            executor_type="local",
            trigger_source="manual",
            progress={"requested_mode": mode, "force_scrape": False, "disable_scraping": False},
        )
    )
    await railway_db.commit()
    return run_id


async def _update_railway_run_status(
    railway_session_factory: async_sessionmaker,
    run_id: str,
    status: str,
    **extra_values,
) -> None:
    async with railway_session_factory() as db:
        values = {"status": status, **extra_values}
        await db.execute(update(Run).where(Run.id == run_id).values(**values))
        await db.commit()


async def run_local_once(
    run_id: str,
    user_id: str,
    local_session_factory: async_sessionmaker,
    railway_session_factory: async_sessionmaker,
    mode: str = "quick",
    force_scrape: bool = False,
    disable_scraping: bool = False,
    claim_token: str | None = None,
) -> None:
    """Process one run using local DB for data, Railway for coordination and sync."""
    try:
        async with railway_session_factory() as rw_db, local_session_factory() as loc_db:
            await mirror_user_and_profile(rw_db, loc_db, user_id)
            await _mirror_run(rw_db, loc_db, run_id, user_id, mode)

        await process_run(
            run_id,
            user_id,
            local_session_factory,
            mode=mode,
            force_scrape=force_scrape,
            disable_scraping=disable_scraping,
            claim_token=claim_token,
        )

        await _update_railway_run_status(railway_session_factory, run_id, "syncing")
        async with local_session_factory() as loc_db, railway_session_factory() as rw_db:
            n = await sync_results_to_railway(loc_db, rw_db, user_id, run_id, top_k=_SYNC_TOP_K)

        await _update_railway_run_status(
            railway_session_factory,
            run_id,
            "completed",
            finished_at=datetime.now(timezone.utc),
            job_count=n,
        )
        logger.info("local_worker: run %s complete, synced %d results", run_id, n)

    except Exception as exc:
        logger.exception("local_worker: run %s failed: %s", run_id, exc)
        await _update_railway_run_status(
            railway_session_factory,
            run_id,
            "failed",
            finished_at=datetime.now(timezone.utc),
            error=str(exc)[:1000],
        )
        raise


async def local_worker_loop(
    local_session_factory: async_sessionmaker,
    railway_session_factory: async_sessionmaker,
) -> None:
    """Poll Railway for local runs and process them."""
    logger.info("Local worker loop started")
    while True:
        for mode in ("quick", "full"):
            req = await _claim_pending_run(railway_session_factory, mode, local_worker=True)
            if req is None:
                continue
            logger.info(
                "local_worker: claimed run %s (mode=%s user=%s)",
                req.run_id,
                mode,
                req.user_id,
            )
            try:
                await run_local_once(
                    req.run_id,
                    req.user_id,
                    local_session_factory,
                    railway_session_factory,
                    mode=req.mode,
                    force_scrape=req.force_scrape,
                    disable_scraping=req.disable_scraping,
                    claim_token=req.claim_token,
                )
            except Exception:
                pass
        await asyncio.sleep(5)
