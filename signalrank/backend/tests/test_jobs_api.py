import pytest
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import ArchivalQueue, JobRaw, JobResult, Run, User


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "jobuser@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "jobuser@test.com", "password": "password123"})
    return r.json()["access_token"]


@pytest.fixture
async def admin_token(client, db: AsyncSession):
    await client.post("/api/auth/register", json={"email": "jobadmin@test.com", "password": "password123"})
    await db.execute(update(User).where(User.email == "jobadmin@test.com").values(is_admin=True))
    await db.commit()
    r = await client.post("/api/auth/login", json={"email": "jobadmin@test.com", "password": "password123"})
    return r.json()["access_token"]


async def test_list_jobs_no_run_returns_empty(client, auth_token):
    r = await client.get("/api/jobs", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["jobs"] == []
    assert data["total"] == 0


async def test_get_profile(client, auth_token):
    r = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    assert "user_id" in r.json()


async def test_patch_profile(client, auth_token):
    r = await client.patch(
        "/api/profile",
        json={"role_intent": "ml_engineer", "min_salary": 5000000},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "updated"


async def test_get_job_not_found(client, auth_token):
    r = await client.get(
        "/api/jobs/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404


async def test_archive_unsuitable_requires_admin(client, auth_token):
    response = await client.post(
        "/api/jobs/archive-unsuitable",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 403


async def test_archive_unsuitable_admin_queues_background_tasks(client, admin_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {admin_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success")
    job = JobRaw(
        job_url="https://example.com/jobs/archivable",
        title="Senior Engineer",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
    )
    db.add_all([run, job])
    await db.flush()
    db.add(
        JobResult(
            run_id=run.id,
            user_id=user_id,
            job_id=job.id,
            final_score=82.0,
            company_tier="tier_s",
        )
    )
    await db.commit()

    response = await client.post(
        "/api/jobs/archive-unsuitable",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["queued"] == 1

    queued = (await db.execute(select(ArchivalQueue))).scalars().all()
    assert len(queued) == 1


async def test_list_jobs_returns_isoformatted_date_posted(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    posted_at = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)
    run = Run(user_id=user_id, status="success")
    job = JobRaw(
        job_url="https://example.com/jobs/iso-date",
        title="ML Engineer",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=posted_at,
    )
    db.add_all([run, job])
    await db.flush()
    db.add(
        JobResult(
            run_id=run.id,
            user_id=user_id,
            job_id=job.id,
            final_score=81.0,
            company_tier="tier_a",
        )
    )
    await db.commit()

    response = await client.get(
        "/api/jobs",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["date_posted"] == posted_at.isoformat()
    assert "description" not in jobs[0]
    assert "fit_band" in jobs[0]
    assert "confidence_band" in jobs[0]
    assert "explanation_summary" in jobs[0]


async def test_list_jobs_sorts_by_date_posted_desc(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success")
    older = JobRaw(
        job_url="https://example.com/jobs/older",
        title="Older Job",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    )
    newer = JobRaw(
        job_url="https://example.com/jobs/newer",
        title="Newer Job",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )
    db.add_all([run, older, newer])
    await db.flush()
    db.add_all(
        [
            JobResult(run_id=run.id, user_id=user_id, job_id=older.id, final_score=70.0, company_tier="tier_a"),
            JobResult(run_id=run.id, user_id=user_id, job_id=newer.id, final_score=60.0, company_tier="tier_a"),
        ]
    )
    await db.commit()

    response = await client.get(
        "/api/jobs?sort=date_posted&sort_dir=desc",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["title"] for job in jobs] == ["Newer Job", "Older Job"]


async def test_jobs_analytics_returns_expected_aggregates(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success", mode="quick")
    jobs = [
        JobRaw(
            job_url="https://example.com/jobs/a",
            title="A",
            company="Acme",
            description="Role A",
            location="Remote",
            site="manual",
        ),
        JobRaw(
            job_url="https://example.com/jobs/b",
            title="B",
            company="Acme",
            description="Role B",
            location="Remote",
            site="linkedin",
        ),
        JobRaw(
            job_url="https://example.com/jobs/c",
            title="C",
            company="Beta",
            description="Role C",
            location="Remote",
            site="manual",
        ),
    ]
    db.add(run)
    db.add_all(jobs)
    await db.flush()
    db.add_all(
        [
            JobResult(run_id=run.id, user_id=user_id, job_id=jobs[0].id, final_score=35.0),
            JobResult(run_id=run.id, user_id=user_id, job_id=jobs[1].id, final_score=75.0),
            JobResult(run_id=run.id, user_id=user_id, job_id=jobs[2].id, final_score=95.0),
        ]
    )
    await db.commit()

    response = await client.get(
        "/api/jobs/analytics",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["score_distribution"] == [
        {"range": "0-40", "count": 1},
        {"range": "40-60", "count": 0},
        {"range": "60-70", "count": 0},
        {"range": "70-80", "count": 1},
        {"range": "80-90", "count": 0},
        {"range": "90-100", "count": 1},
    ]
    assert payload["top_companies"][0] == {"company": "Acme", "count": 2}
    assert {"site": "manual", "count": 2} in payload["sites"]


async def test_get_job_includes_agentic_summary_fields(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success")
    job = JobRaw(
        job_url="https://example.com/jobs/agentic",
        title="Senior ML Engineer",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
    )
    db.add_all([run, job])
    await db.flush()
    db.add(
        JobResult(
            run_id=run.id,
            user_id=user_id,
            job_id=job.id,
            final_score=86.0,
            fit_band="strong_fit",
            confidence_band="high",
            explanation_summary="Strong fit | lane: direct",
        )
    )
    await db.commit()

    response = await client.get(
        f"/api/jobs/{job.id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["fit_band"] == "strong_fit"
    assert payload["confidence_band"] == "high"
    assert payload["explanation_summary"] == "Strong fit | lane: direct"
