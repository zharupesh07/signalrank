import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import User, Run
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def auth_token(client, db: AsyncSession):
    await client.post("/api/auth/register", json={"email": "runner@test.com", "password": "password123"})
    from api.models import Profile
    user = (await db.execute(select(User).where(User.email == "runner@test.com"))).scalar_one()
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    profile.onboarding_complete = True
    await db.commit()
    r = await client.post("/api/auth/login", json={"email": "runner@test.com", "password": "password123"})
    return r.json()["access_token"]


async def test_trigger_run_returns_run_id(client, auth_token):
    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 202
    data = r.json()
    assert "run_id" in data
    assert data["status"] == "pending"


async def test_trigger_full_run_returns_run_id(client, auth_token):
    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"mode": "full"},
    )
    assert r.status_code == 202
    data = r.json()
    assert "run_id" in data
    assert data["status"] == "pending"


async def test_trigger_run_does_not_require_local_queue_when_api_worker_disabled(
    client,
    auth_token,
    db: AsyncSession,
    monkeypatch,
):
    import api.routes.runs as runs_route

    monkeypatch.setattr(
        runs_route,
        "api_runtime_flags",
        lambda: {"run_api_worker": False},
    )

    def _should_not_queue():
        raise AssertionError("API route should not enqueue when local API worker is disabled")

    monkeypatch.setattr(runs_route, "get_queue", _should_not_queue)

    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 202

    run_id = r.json()["run_id"]
    run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert run.status == "pending"
    assert run.mode == "quick"
    assert run.progress == {"requested_mode": "quick", "force_scrape": False, "disable_scraping": False, "run_kind": "manual_run"}


async def test_trigger_full_run_persists_mode(client, auth_token, db: AsyncSession):
    response = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"mode": "full"},
    )
    assert response.status_code == 202
    run = (
        await db.execute(select(Run).where(Run.id == response.json()["run_id"]))
    ).scalar_one()
    assert run.mode == "full"
    assert run.progress == {"requested_mode": "full", "force_scrape": True, "disable_scraping": False, "run_kind": "manual_refresh"}


async def test_trigger_run_can_disable_scraping(client, auth_token, db: AsyncSession):
    response = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"disable_scraping": True},
    )
    assert response.status_code == 202
    run = (
        await db.execute(select(Run).where(Run.id == response.json()["run_id"]))
    ).scalar_one()
    assert run.progress == {"requested_mode": "quick", "force_scrape": False, "disable_scraping": True, "run_kind": "rerank_only"}


async def test_trigger_run_reuses_existing_active_run(client, auth_token, db: AsyncSession):
    user = (await db.execute(select(User).where(User.email == "runner@test.com"))).scalar_one()
    existing = Run(
        user_id=user.id,
        status="pending",
        mode="quick",
        progress={"requested_mode": "quick", "force_scrape": False, "disable_scraping": False},
    )
    db.add(existing)
    await db.commit()

    response = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 202
    assert response.json()["run_id"] == existing.id


async def test_rank_existing_jobs_defaults_to_quick_without_scraping(client, auth_token, db: AsyncSession):
    response = await client.post(
        "/api/runs/rank-existing",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 202
    run = (
        await db.execute(select(Run).where(Run.id == response.json()["run_id"]))
    ).scalar_one()
    assert run.mode == "quick"
    assert run.progress == {"requested_mode": "quick", "force_scrape": False, "disable_scraping": True, "run_kind": "rerank_only"}


async def test_rank_existing_jobs_can_request_full_mode(client, auth_token, db: AsyncSession):
    response = await client.post(
        "/api/runs/rank-existing",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"mode": "full", "disable_scraping": False},
    )
    assert response.status_code == 202
    run = (
        await db.execute(select(Run).where(Run.id == response.json()["run_id"]))
    ).scalar_one()
    assert run.mode == "full"
    assert run.progress == {"requested_mode": "full", "force_scrape": False, "disable_scraping": True, "run_kind": "rerank_only"}


async def test_get_run_status(client, auth_token):
    trigger = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    run_id = trigger.json()["run_id"]
    r = await client.get(
        f"/api/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id
    assert r.json()["status"] in ("pending", "running", "success", "failed")


async def test_get_latest_run(client, auth_token):
    await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    r = await client.get(
        "/api/runs/latest",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200


async def test_get_run_status_includes_error(client, auth_token, db: AsyncSession):
    run = Run(user_id=(await db.execute(select(User).where(User.email == "runner@test.com"))).scalar_one().id, status="failed", error="ValueError: boom")
    db.add(run)
    await db.commit()

    r = await client.get(
        f"/api/runs/{run.id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    assert r.json()["error"] == "ValueError: boom"


async def test_get_run_status_includes_corpus_metadata(client, auth_token, db: AsyncSession):
    user = (await db.execute(select(User).where(User.email == "runner@test.com"))).scalar_one()
    run = Run(
        user_id=user.id,
        status="success",
        job_count=83,
        scrape_count=12,
        progress={
            "run_kind": "rerank_only",
            "corpus_source": "latest_scrape_run",
            "corpus_job_count": 240,
            "scored_job_count": 83,
            "shown_job_count": 83,
        },
    )
    db.add(run)
    await db.commit()

    r = await client.get(
        f"/api/runs/{run.id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["corpus_source"] == "latest_scrape_run"
    assert payload["corpus_count"] == 240
    assert payload["scored_count"] == 83
    assert payload["shown_count"] == 83


async def test_stop_pending_run(client, auth_token):
    # Trigger a run
    trigger = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    run_id = trigger.json()["run_id"]

    # Stop the run
    r = await client.post(
        f"/api/runs/{run_id}/stop",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["stopped"] is True
    assert data["status"] == "cancelled"

    # Verify run status is cancelled
    status_r = await client.get(
        f"/api/runs/{run_id}/status",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert status_r.status_code == 200
    assert status_r.json()["status"] == "cancelled"


async def test_stop_active_run_marks_cancel_requested(client, auth_token, db: AsyncSession):
    user = (await db.execute(select(User).where(User.email == "runner@test.com"))).scalar_one()
    run = Run(user_id=user.id, status="scraping", mode="quick")
    db.add(run)
    await db.commit()

    response = await client.post(
        f"/api/runs/{run.id}/stop",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"

    refreshed = (await db.execute(select(Run).where(Run.id == run.id))).scalar_one()
    assert refreshed.cancel_requested is True
    assert refreshed.status == "scraping"


async def test_stop_nonexistent_run(client, auth_token):
    fake_run_id = str(uuid.uuid4())
    r = await client.post(
        f"/api/runs/{fake_run_id}/stop",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404


async def test_stop_another_users_run(client, auth_token, db: AsyncSession):
    # Create another user and a run
    other_user = User(id=str(uuid.uuid4()), email="other@test.com", password_hash="mock", provider="credentials")
    db.add(other_user)
    await db.flush()
    other_run = Run(user_id=other_user.id, status="pending")
    db.add(other_run)
    await db.commit()

    # Try to stop the other user's run
    r = await client.post(
        f"/api/runs/{other_run.id}/stop",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404  # Should not be able to stop another user's run


@pytest.mark.asyncio
async def test_trigger_run_with_executor_type_local_non_admin_forbidden(client, auth_token, db: AsyncSession):
    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"executor_type": "local"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_trigger_run_with_executor_type_local(client, db: AsyncSession):
    await client.post("/api/auth/register", json={"email": "admin_runner@test.com", "password": "password123"})
    from api.models import Profile
    user = (await db.execute(select(User).where(User.email == "admin_runner@test.com"))).scalar_one()
    user.is_admin = True
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    profile.onboarding_complete = True
    await db.commit()
    r = await client.post("/api/auth/login", json={"email": "admin_runner@test.com", "password": "password123"})
    admin_token = r.json()["access_token"]

    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"executor_type": "local"},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    from api.models import Run
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.executor_type == "local"


@pytest.mark.asyncio
async def test_trigger_run_defaults_executor_type_to_cloud(client, auth_token, db: AsyncSession):
    r = await client.post(
        "/api/runs/trigger",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    from api.models import Run
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.executor_type in (None, "cloud")
