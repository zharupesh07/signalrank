"""Tests for batch/local_sync.py — syncing top-100 from local DB to Railway DB."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, JobResult, Run, User
from batch.local_sync import sync_results_to_railway


async def _make_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, email=f"{user_id}@test.com", password_hash="x"))
    await db.flush()
    return user_id


async def _make_run(db: AsyncSession, user_id: str) -> str:
    run_id = str(uuid.uuid4())
    db.add(Run(id=run_id, user_id=user_id, status="ranking", mode="quick"))
    await db.flush()
    return run_id


async def _make_job(db: AsyncSession, url: str) -> str:
    job_id = str(uuid.uuid4())
    db.add(JobRaw(
        id=job_id,
        job_url=url,
        title="Test Engineer",
        company="TestCo",
        description="A test job description with enough text.",
        location="Remote",
        site="linkedin",
        date_posted=datetime.now(timezone.utc),
    ))
    await db.flush()
    return job_id


async def _make_result(db: AsyncSession, user_id, run_id, job_id, score) -> None:
    db.add(JobResult(
        id=str(uuid.uuid4()),
        user_id=user_id,
        run_id=run_id,
        job_id=job_id,
        final_score=score,
        skills_score=50.0,
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_sync_results_upserts_jobs_and_results(db: AsyncSession):
    """sync_results_to_railway upserts top-k jobs_raw and job_results to target DB."""
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)
    job_id = await _make_job(db, "https://example.com/job/1")
    await _make_result(db, user_id, run_id, job_id, 95.0)
    await db.commit()

    n = await sync_results_to_railway(db, db, user_id, run_id, top_k=100)
    assert n == 1


@pytest.mark.asyncio
async def test_sync_returns_zero_for_empty_results(db: AsyncSession):
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)
    await db.commit()

    n = await sync_results_to_railway(db, db, user_id, run_id, top_k=100)
    assert n == 0


@pytest.mark.asyncio
async def test_sync_respects_top_k(db: AsyncSession):
    """Only top-k results by final_score are synced."""
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)

    for i in range(5):
        job_id = await _make_job(db, f"https://example.com/job/{i}")
        await _make_result(db, user_id, run_id, job_id, float(i * 10))
    await db.commit()

    n = await sync_results_to_railway(db, db, user_id, run_id, top_k=3)
    assert n == 3
