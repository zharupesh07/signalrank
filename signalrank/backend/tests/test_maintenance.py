from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from api.auth import create_access_token
from api.models import (
    ArchivalQueue,
    GenerationQueue,
    JobRaw,
    JobResult,
    RecruiterRefreshTask,
    Run,
    User,
    ScrapeQueryCache,
    TailoredResume,
)
from batch.maintenance import (
    prune_completed_runs_and_results,
    prune_llm_cache,
    prune_recruiter_refresh_tasks,
    prune_scrape_query_cache,
    prune_terminal_queues,
)


async def _admin_token(client, db):
    email = "prune-admin@test.com"
    await client.post("/api/auth/register", json={"email": email, "password": "password123"})
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    user.is_admin = True
    await db.commit()
    return create_access_token(user.id, user.email, is_admin=True)


async def test_prune_scrape_query_cache_removes_stale_rows(db):
    stale = ScrapeQueryCache(
        provider="jobspy",
        site="remoteok",
        term_normalized="python",
        location_normalized="",
        country_normalized="",
        hours_old=24,
        result_count=1,
        fresh_until=datetime.now(timezone.utc) - timedelta(days=15),
    )
    fresh = ScrapeQueryCache(
        provider="jobspy",
        site="remoteok",
        term_normalized="go",
        location_normalized="",
        country_normalized="",
        hours_old=24,
        result_count=1,
        fresh_until=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add_all([stale, fresh])
    await db.commit()

    deleted = await prune_scrape_query_cache(db, now=datetime.now(timezone.utc))
    assert deleted == 1
    assert (await db.execute(select(ScrapeQueryCache))).scalars().all() == [fresh]


async def test_prune_llm_cache_removes_old_rows(db):
    await db.execute(
        text("INSERT INTO llm_cache (prompt_hash, response_json, created_at) VALUES (:prompt_hash, CAST(:response_json AS jsonb), :created_at)"),
        {
            "prompt_hash": "old",
            "response_json": "{}",
            "created_at": datetime.now(timezone.utc) - timedelta(days=31),
        },
    )
    await db.execute(
        text("INSERT INTO llm_cache (prompt_hash, response_json, created_at) VALUES (:prompt_hash, CAST(:response_json AS jsonb), :created_at)"),
        {
            "prompt_hash": "fresh",
            "response_json": "{}",
            "created_at": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    deleted = await prune_llm_cache(db, now=datetime.now(timezone.utc))
    assert deleted == 1


async def test_prune_terminal_queues_keeps_pending_rows(db):
    user = User(email="maint@test.com", password_hash="x")
    job_pending = JobRaw(job_url="https://example.com/pending", title="Pending", company="A")
    job_done = JobRaw(job_url="https://example.com/done", title="Done", company="A")
    run = Run(user=user, status="success", finished_at=datetime.now(timezone.utc))
    db.add_all([user, job_pending, job_done, run])
    await db.flush()
    jr_pending = JobResult(run_id=run.id, user_id=user.id, job_id=job_pending.id, final_score=90.0)
    jr_done = JobResult(run_id=run.id, user_id=user.id, job_id=job_done.id, final_score=90.0)
    db.add_all([jr_pending, jr_done])
    await db.flush()
    gen_pending = GenerationQueue(user_id=user.id, job_id=job_pending.id, status="pending")
    gen_done = GenerationQueue(user_id=user.id, job_id=job_done.id, status="done")
    arch_pending = ArchivalQueue(user_id=user.id, job_result_id=jr_pending.id, status="pending")
    arch_done = ArchivalQueue(user_id=user.id, job_result_id=jr_done.id, status="done")
    db.add_all([gen_pending, gen_done, arch_pending, arch_done])
    await db.commit()

    deleted = await prune_terminal_queues(db)
    assert deleted == {"generation_queue": 1, "archival_queue": 1}

    remaining_generation = (await db.execute(select(GenerationQueue))).scalars().all()
    remaining_archival = (await db.execute(select(ArchivalQueue))).scalars().all()
    assert remaining_generation == [gen_pending]
    assert remaining_archival == [arch_pending]


async def test_prune_completed_runs_and_results_prunes_related_rows(db):
    user = User(email="cleanup@test.com", password_hash="x")
    old_run = Run(
        user=user,
        status="success",
        finished_at=datetime.now(timezone.utc) - timedelta(days=61),
    )
    recent_run = Run(
        user=user,
        status="success",
        finished_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add_all([user, old_run, recent_run])
    await db.flush()

    old_job = JobRaw(job_url="https://example.com/old", title="Old", company="A")
    recent_job = JobRaw(job_url="https://example.com/recent", title="Recent", company="B")
    db.add_all([old_job, recent_job])
    await db.flush()

    old_result = JobResult(run_id=old_run.id, user_id=user.id, job_id=old_job.id, final_score=90.0)
    recent_result = JobResult(run_id=recent_run.id, user_id=user.id, job_id=recent_job.id, final_score=90.0)
    db.add_all([old_result, recent_result])
    db.add_all(
        [
            TailoredResume(user_id=user.id, job_id=old_job.id, template="classic"),
            TailoredResume(user_id=user.id, job_id=recent_job.id, template="classic"),
        ]
    )
    await db.commit()

    deleted = await prune_completed_runs_and_results(db, now=datetime.now(timezone.utc))
    assert deleted["runs"] == 1
    assert deleted["job_results"] == 1
    assert deleted["tailored_resumes"] == 1


async def test_prune_recruiter_refresh_tasks_removes_finished_old_rows(db):
    user = User(email="refresh@test.com", password_hash="x")
    db.add(user)
    await db.flush()
    old = RecruiterRefreshTask(
        user_id=user.id,
        status="done",
        finished_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    fresh = RecruiterRefreshTask(
        user_id=user.id,
        status="done",
        finished_at=datetime.now(timezone.utc),
    )
    db.add_all([old, fresh])
    await db.commit()

    deleted = await prune_recruiter_refresh_tasks(db, now=datetime.now(timezone.utc))
    assert deleted == 1


async def test_admin_maintenance_prune_endpoint(client, db):
    admin_token = await _admin_token(client, db)
    user = User(email="prune@test.com", password_hash="x")
    stale = ScrapeQueryCache(
        provider="jobspy",
        site="remoteok",
        term_normalized="python",
        location_normalized="",
        country_normalized="",
        hours_old=24,
        result_count=1,
        fresh_until=datetime.now(timezone.utc) - timedelta(days=15),
    )
    db.add_all([user, stale])
    await db.commit()

    response = await client.post(
        "/api/admin/maintenance/prune",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "scrape_query_cache" in payload["deleted"]
