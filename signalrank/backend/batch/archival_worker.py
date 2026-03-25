"""Archival worker: LLM-based job suitability evaluation.

Polls archival_queue, sends job + user profile to OpenRouter free model,
marks unsuitable jobs as archived. Only evaluates SS/S/A tier companies.

Pattern mirrors batch/resume_worker.py exactly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import ArchivalQueue, JobRaw, JobResult, Profile
from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

CONCURRENCY = 3
MAX_TASK_RETRIES = 3
POLL_INTERVAL = 5

SYSTEM_PROMPT = """You evaluate whether a job posting is suitable for a candidate.
Return ONLY valid JSON: {"suitable": true/false, "reason": "brief 1-sentence explanation"}

Rules for marking UNSUITABLE (suitable=false):
- Requires significantly more experience than the candidate's max years
- Role is clearly unrelated to the candidate's target roles or skills
- Location mismatch with no remote option mentioned
- Too junior (well below candidate's min years, e.g. internship for senior candidate)
- Role is in a completely different domain (e.g. sales role for an engineer)

IMPORTANT: When in doubt, mark as suitable. Do NOT over-filter. Only archive obvious mismatches."""


def _build_user_prompt(profile: Profile, job: JobRaw, job_result: JobResult) -> str:
    target_roles = profile.target_roles or []
    skills = profile.skills or []
    locations = profile.preferred_locations or []
    min_yoe = profile.min_yoe or 0
    max_yoe = profile.max_yoe or 20

    parts = [
        "CANDIDATE PROFILE:",
        f"- Role intent: {profile.role_intent or 'not specified'}",
        f"- Target roles: {', '.join(target_roles) if isinstance(target_roles, list) else str(target_roles)}",
        f"- Experience range: {min_yoe}-{max_yoe} years",
        f"- Key skills: {', '.join(skills[:15]) if isinstance(skills, list) else str(skills)}",
        f"- Preferred locations: {', '.join(locations) if isinstance(locations, list) else str(locations)}",
        "",
        "JOB POSTING:",
        f"- Title: {job.title or 'Unknown'}",
        f"- Company: {job.company or 'Unknown'} (Tier: {job_result.company_tier or 'Unknown'})",
        f"- Location: {job.location or 'Not specified'}",
        f"- Contract: {'Yes' if job_result.is_contract else 'No'}",
        f"- Description:\n{(job.description or '')[:2000]}",
    ]
    return "\n".join(parts)


async def evaluate_job(
    task: ArchivalQueue,
    db: AsyncSession,
    llm: OpenRouterClient,
) -> None:
    """Evaluate one job for suitability. Idempotent — skips if already evaluated."""
    jr_res = await db.execute(
        select(JobResult).where(JobResult.id == task.job_result_id)
    )
    job_result = jr_res.scalar_one_or_none()
    if not job_result:
        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(status="failed", error="JobResult not found")
        )
        await db.commit()
        return

    if job_result.archived_by_llm is not None:
        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(status="done")
        )
        await db.commit()
        return

    profile_res = await db.execute(
        select(Profile).where(Profile.user_id == task.user_id)
    )
    profile = profile_res.scalar_one_or_none()
    if not profile:
        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(status="failed", error="No profile found for user")
        )
        await db.commit()
        return

    job_res = await db.execute(
        select(JobRaw).where(JobRaw.id == job_result.job_id)
    )
    job = job_res.scalar_one_or_none()
    if not job:
        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(status="failed", error="Job not found")
        )
        await db.commit()
        return

    user_prompt = _build_user_prompt(profile, job, job_result)

    try:
        result = await llm.llm_json(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=256,
            temperature=0.0,
        )

        suitable = result.get("suitable", True)
        reason = result.get("reason", "")

        if result.get("_error"):
            raise RuntimeError(f"LLM failed: {result['_error']}")

        job_result.archived_by_llm = not suitable
        job_result.archival_reason = reason[:500] if reason else None

        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(status="done")
        )
        await db.commit()

        action = "ARCHIVED" if not suitable else "KEPT"
        logger.info(
            "%s job %s (%s @ %s): %s",
            action, job_result.job_id, job.title, job.company, reason[:80],
        )

    except Exception as e:
        logger.warning("Archival evaluation failed for job_result=%s: %s", task.job_result_id, e)
        await db.rollback()
        new_retry_count = (task.retry_count or 0) + 1
        if new_retry_count >= MAX_TASK_RETRIES:
            new_status = "failed"
            next_retry_at = None
        else:
            new_status = "pending"
            backoff = min(2 ** (new_retry_count + 1), 120) + random.uniform(0, 10)
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        await db.execute(
            update(ArchivalQueue).where(ArchivalQueue.id == task.id)
            .values(
                status=new_status,
                error=str(e),
                retry_count=new_retry_count,
                next_retry_at=next_retry_at,
            )
        )
        await db.commit()


async def recover_stuck_archival_tasks(db: AsyncSession) -> int:
    """Reset tasks left in 'running' state from a prior crash back to 'pending'."""
    result = await db.execute(
        update(ArchivalQueue)
        .where(ArchivalQueue.status == "running")
        .values(status="pending", next_retry_at=None)
        .returning(ArchivalQueue.id)
    )
    count = len(result.fetchall())
    if count:
        await db.commit()
    return count


async def archival_worker_loop(
    session_factory: async_sessionmaker,
    llm: OpenRouterClient,
) -> None:
    """Poll archival_queue for pending tasks, process up to CONCURRENCY at a time."""
    logger.info("Archival worker started")

    async def _run_task(t):
        async with session_factory() as task_db:
            await evaluate_job(t, task_db, llm)

    while True:
        tasks: list = []
        try:
            async with session_factory() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(ArchivalQueue)
                    .where(
                        ArchivalQueue.status == "pending",
                        (ArchivalQueue.next_retry_at.is_(None)) | (ArchivalQueue.next_retry_at <= now),
                    )
                    .order_by(ArchivalQueue.created_at)
                    .limit(CONCURRENCY)
                    .with_for_update(skip_locked=True)
                )
                tasks = result.scalars().all()

                if tasks:
                    for task in tasks:
                        await db.execute(
                            update(ArchivalQueue)
                            .where(ArchivalQueue.id == task.id)
                            .values(status="running")
                        )
                    await db.commit()

            if tasks:
                await asyncio.gather(
                    *[_run_task(t) for t in tasks],
                    return_exceptions=True,
                )
        except Exception:
            logger.exception("Archival worker loop error")

        await asyncio.sleep(POLL_INTERVAL)
