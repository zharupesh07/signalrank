import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import User, Run
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "runner@test.com", "password": "pass"})
    r = await client.post("/api/auth/login", json={"email": "runner@test.com", "password": "pass"})
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
