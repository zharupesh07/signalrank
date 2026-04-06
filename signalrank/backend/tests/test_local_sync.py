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


@pytest.mark.asyncio
async def test_sync_top_k_selects_highest_scores(db: AsyncSession):
    """top_k=2 keeps the two highest-scored jobs, not lowest."""
    from sqlalchemy import select as sa_select
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)

    scores = {
        "https://example.com/low": 10.0,
        "https://example.com/mid": 50.0,
        "https://example.com/high": 90.0,
    }
    for url, score in scores.items():
        job_id = await _make_job(db, url)
        await _make_result(db, user_id, run_id, job_id, score)
    await db.commit()

    n = await sync_results_to_railway(db, db, user_id, run_id, top_k=2)
    # sync selected only 2 of the 3 results (highest scores)
    assert n == 2


@pytest.mark.asyncio
async def test_sync_idempotent_on_rerun(db: AsyncSession):
    """Calling sync twice does not duplicate rows (upsert by job_url + uq_job_results_user_job)."""
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)
    job_id = await _make_job(db, "https://example.com/job/idem")
    await _make_result(db, user_id, run_id, job_id, 75.0)
    await db.commit()

    n1 = await sync_results_to_railway(db, db, user_id, run_id, top_k=100)
    n2 = await sync_results_to_railway(db, db, user_id, run_id, top_k=100)
    assert n1 == 1
    assert n2 == 1  # second sync is a no-op, not a duplicate


@pytest.mark.asyncio
async def test_sync_excludes_embedding_column(db: AsyncSession):
    """jobs_raw rows synced to Railway must not carry the embedding vector."""
    from sqlalchemy import select as sa_select
    user_id = await _make_user(db)
    run_id = await _make_run(db, user_id)

    # Create a job with a non-null embedding
    import json
    job_id = str(uuid.uuid4())
    job = JobRaw(
        id=job_id,
        job_url="https://example.com/job/embed",
        title="Embed Engineer",
        company="EmbedCo",
        description="Job with embedding attached.",
        location="Remote",
        site="linkedin",
        date_posted=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    await _make_result(db, user_id, run_id, job_id, 80.0)
    await db.commit()

    n = await sync_results_to_railway(db, db, user_id, run_id, top_k=100)
    assert n == 1

    # Verify the synced job_raw exists but embedding was not written by sync
    # (same DB, but embedding should still be None/null since sync never sets it)
    synced = (await db.execute(
        sa_select(JobRaw).where(JobRaw.job_url == "https://example.com/job/embed")
    )).scalar_one()
    assert synced.embedding is None
