import pytest


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "jobuser@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "jobuser@test.com", "password": "password123"})
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
