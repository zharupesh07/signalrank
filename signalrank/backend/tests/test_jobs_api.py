import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import create_access_token
from api.models import ArchivalQueue, JobPreferenceMemory, JobRaw, JobResult, Profile, Run, User


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
    assert "rank_reason_up" in jobs[0]
    assert "rank_reason_down" in jobs[0]
    assert jobs[0]["rank_stage"] == "deterministic"
    assert jobs[0]["freshness_bucket"] == "aging"
    assert jobs[0]["is_direct_source"] is False
    assert jobs[0]["preference_bucket"] in {"Top fit", "Strong fit", "Possible fit", "Stretch", "Hide"}
    assert isinstance(jobs[0]["preference_tags"], list)


async def test_list_jobs_uses_requested_timezone(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    posted_at = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)
    run = Run(user_id=user_id, status="success")
    job = JobRaw(
        job_url="https://example.com/jobs/tz",
        title="Timezone Job",
        company="Example Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=posted_at,
    )
    db.add_all([run, job])
    await db.flush()
    db.add(JobResult(run_id=run.id, user_id=user_id, job_id=job.id, final_score=81.0))
    await db.commit()

    response = await client.get(
        "/api/jobs",
        headers={
            "Authorization": f"Bearer {auth_token}",
            "X-User-Timezone": "America/New_York",
        },
    )
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert jobs[0]["date_posted"].endswith("-04:00")


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


async def test_list_jobs_filters_company_tiers_including_legacy_values(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success")
    ss_job = JobRaw(
        job_url="https://example.com/jobs/ss",
        title="SS Job",
        company="Elite Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )
    legacy_s_job = JobRaw(
        job_url="https://example.com/jobs/legacy-s",
        title="Legacy S Job",
        company="Strong Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )
    b_job = JobRaw(
        job_url="https://example.com/jobs/b",
        title="B Job",
        company="Okay Corp",
        description="Role",
        location="Remote",
        site="manual",
        date_posted=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )
    db.add_all([run, ss_job, legacy_s_job, b_job])
    await db.flush()
    db.add_all(
        [
            JobResult(run_id=run.id, user_id=user_id, job_id=ss_job.id, final_score=91.0, company_tier="tier_ss"),
            JobResult(run_id=run.id, user_id=user_id, job_id=legacy_s_job.id, final_score=81.0, company_tier="S"),
            JobResult(run_id=run.id, user_id=user_id, job_id=b_job.id, final_score=71.0, company_tier="tier_b"),
        ]
    )
    await db.commit()

    response = await client.get(
        "/api/jobs?tiers=tier_ss&tiers=tier_s",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["title"] for job in jobs] == ["SS Job", "Legacy S Job"]
    assert jobs[1]["company_tier"] == "tier_s"


@pytest.mark.asyncio
async def test_list_jobs_scopes_filters_to_latest_success_run(client, auth_token, db: AsyncSession):
    user_id = str(uuid.uuid4())
    user = User(id=user_id, email="latest-run@test.com", password_hash="x")
    db.add(user)

    older_run = Run(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="success",
        finished_at=datetime.now(timezone.utc) - timedelta(days=1),
        job_count=1,
    )
    latest_run = Run(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="success",
        finished_at=datetime.now(timezone.utc),
        job_count=1,
    )
    db.add_all([older_run, latest_run])
    await db.flush()

    older_job = JobRaw(
        job_url="https://example.com/older-ss",
        title="Old SS Job",
        company="OlderCo",
        description="older",
        location="Remote",
        site="indeed",
        date_posted=datetime.now(timezone.utc),
    )
    latest_job = JobRaw(
        job_url="https://example.com/latest-b",
        title="Latest B Job",
        company="LatestCo",
        description="latest",
        location="Remote",
        site="indeed",
        date_posted=datetime.now(timezone.utc),
    )
    db.add_all([older_job, latest_job])
    await db.flush()

    db.add_all(
        [
            JobResult(
                run_id=older_run.id,
                user_id=user_id,
                job_id=older_job.id,
                final_score=91.0,
                company_tier="tier_ss",
            ),
            JobResult(
                run_id=latest_run.id,
                user_id=user_id,
                job_id=latest_job.id,
                final_score=81.0,
                company_tier="tier_b",
            ),
        ]
    )
    await db.commit()

    response = await client.get(
        "/api/jobs?tiers=tier_ss",
        headers={"Authorization": f"Bearer {create_access_token(user_id, user.email, is_admin=False)}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["jobs"] == []


@pytest.mark.asyncio
async def test_list_jobs_ignores_success_runs_with_null_finished_at(client, auth_token, db: AsyncSession):
    user_id = str(uuid.uuid4())
    email = "null-finished@test.com"
    user = User(id=user_id, email=email, password_hash="x")
    db.add(user)

    bogus_latest = Run(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="success",
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        job_count=0,
    )
    real_run = Run(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="success",
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        finished_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        job_count=1,
    )
    db.add_all([bogus_latest, real_run])
    await db.flush()

    real_job = JobRaw(
        job_url="https://example.com/real-job",
        title="Real Job",
        company="RealCo",
        description="real",
        location="Remote",
        site="indeed",
        date_posted=datetime.now(timezone.utc),
    )
    db.add(real_job)
    await db.flush()
    db.add(
        JobResult(
            run_id=real_run.id,
            user_id=user_id,
            job_id=real_job.id,
            final_score=88.0,
            company_tier="tier_a",
        )
    )
    await db.commit()

    response = await client.get(
        "/api/jobs",
        headers={"Authorization": f"Bearer {create_access_token(user_id, email, is_admin=False)}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["title"] == "Real Job"


@pytest.mark.asyncio
async def test_job_feedback_reranks_shortlist_and_persists_preferences(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success", started_at=datetime.now(timezone.utc) - timedelta(hours=1), finished_at=datetime.now(timezone.utc))
    bangalore_job = JobRaw(
        job_url="https://example.com/jobs/bangalore",
        title="AI Platform Engineer",
        company="City Corp",
        description="Platform engineering for copilots",
        location="Bangalore, India",
        site="indeed",
        date_posted=datetime.now(timezone.utc),
    )
    pune_job = JobRaw(
        job_url="https://example.com/jobs/pune",
        title="AI Platform Engineer",
        company="Remote Corp",
        description="Copilot platform engineering",
        location="Pune, India",
        site="greenhouse",
        date_posted=datetime.now(timezone.utc),
    )
    db.add_all([run, bangalore_job, pune_job])
    await db.flush()
    db.add_all(
        [
            JobResult(run_id=run.id, user_id=user_id, job_id=bangalore_job.id, final_score=90.0, company_tier="tier_a"),
            JobResult(run_id=run.id, user_id=user_id, job_id=pune_job.id, final_score=86.0, company_tier="tier_a"),
        ]
    )
    await db.commit()

    baseline = await client.get("/api/jobs", headers={"Authorization": f"Bearer {auth_token}"})
    assert baseline.status_code == 200
    assert [job["title"] for job in baseline.json()["jobs"]] == ["AI Platform Engineer", "AI Platform Engineer"]
    assert baseline.json()["jobs"][0]["location"] == "Bangalore, India"

    feedback = await client.post(
        "/api/jobs/feedback",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "feedback_text": "prefer Pune over Bangalore and show more copilot jobs",
            "page": 1,
            "limit": 50,
            "sort": "final_score",
            "sort_dir": "desc",
            "show_archived": True,
            "min_score": 0,
            "tiers": [],
            "job_type": "all",
            "sites": [],
            "date_range": "any",
        },
    )
    assert feedback.status_code == 200
    payload = feedback.json()
    jobs = payload["jobs_payload"]["jobs"]
    assert jobs[0]["location"] == "Pune, India"
    assert "prefers Pune" in jobs[0]["preference_tags"]
    assert payload["preferences"]["summary_chips"]

    memory = (await db.execute(select(JobPreferenceMemory).where(JobPreferenceMemory.user_id == user_id))).scalar_one_or_none()
    assert memory is not None
    assert memory.state_json["location_preferences"]

    preferences = await client.get("/api/jobs/preferences", headers={"Authorization": f"Bearer {auth_token}"})
    assert preferences.status_code == 200
    prefs_payload = preferences.json()
    assert prefs_payload["recent_feedback"][0]["feedback_text"] == "prefer Pune over Bangalore and show more copilot jobs"


@pytest.mark.asyncio
async def test_reset_preferences_clears_learned_state(client, auth_token, db: AsyncSession):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]
    db.add(
        JobPreferenceMemory(
            user_id=user_id,
            state_json={
                "location_preferences": [{"value": "pune", "label": "Pune", "weight": 2.0}],
                "role_preferences": [],
                "positive_tags": [],
                "negative_tags": [],
                "hidden_companies": [],
                "preferred_sources": [],
                "work_mode_preferences": [],
                "positive_examples": [],
                "negative_examples": [],
                "explanation_snippets": ["Pune preferred"],
            },
        )
    )
    await db.commit()

    response = await client.post(
        "/api/jobs/preferences/reset",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"clear_all": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_learned_preferences"] is False
    assert payload["state"]["location_preferences"] == []


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


async def test_jobs_analytics_uses_cached_payload(client, auth_token, db: AsyncSession, monkeypatch):
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]

    run = Run(user_id=user_id, status="success", mode="quick")
    job = JobRaw(
        job_url="https://example.com/jobs/cache",
        title="Cache",
        company="Acme",
        description="Role",
        location="Remote",
        site="manual",
    )
    db.add_all([run, job])
    await db.flush()
    db.add(JobResult(run_id=run.id, user_id=user_id, job_id=job.id, final_score=75.0))
    await db.commit()

    call_count = {"count": 0}
    original_execute = db.execute

    async def tracking_execute(*args, **kwargs):
        call_count["count"] += 1
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(db, "execute", tracking_execute)

    first = await client.get(
        "/api/jobs/analytics",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    second = await client.get(
        "/api/jobs/analytics",
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["count"] > 0


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


async def test_profile_fresh_preview_returns_rows(client, auth_token, db: AsyncSession, monkeypatch):
    import api.routes.jobs as jobs_route

    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    user_id = me.json()["user_id"]
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()
    profile.resume_text = "Senior AI Platform Engineer with MLOps and agent systems experience"
    await db.commit()

    async def _fake_generate(**kwargs):
        assert kwargs["resume_text"] == profile.resume_text
        return {
            "output_csv": "/tmp/profile_fresh.csv",
            "summary_json": "/tmp/profile_fresh.summary.json",
            "scraped_jobs": 10,
            "jobs_scored": 3,
            "companies_exported": 2,
            "rejection_counts": {"role_mismatch": 7},
            "rows": [
                {
                    "company_rank": 1,
                    "company": "Acme",
                    "company_tier": "tier_s",
                    "role_bucket": "agentic",
                    "best_job_title": "Senior Agent Engineer",
                    "best_job_location": "Remote, India",
                    "location_bucket": "top",
                    "remote_policy_match": "india_safe",
                    "yoe_match_band": "ideal",
                    "site": "greenhouse",
                    "best_job_url": "https://example.com/1",
                    "score": 91.0,
                    "jobs_considered_for_company": 2,
                }
            ],
        }

    monkeypatch.setattr(jobs_route, "generate_profile_fresh_company_rank", _fake_generate)

    response = await client.post(
        "/api/jobs/profile-fresh",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "limit": 30,
            "queries": ["MLOps Engineer"],
            "locations": ["Remote", "Pune"],
            "sources": ["ats_direct"],
            "companies": ["Snowflake"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["companies_exported"] == 2
    assert payload["scraped_jobs"] == 10
    assert payload["rows"][0]["company"] == "Acme"
