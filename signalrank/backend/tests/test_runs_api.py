import pytest


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
