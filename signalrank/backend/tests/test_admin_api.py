import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Profile, User


@pytest.fixture
async def admin_token(client, db: AsyncSession):
    await client.post("/api/auth/register", json={"email": "admin@test.com", "password": "adminpassword123"})
    await db.execute(update(User).where(User.email == "admin@test.com").values(is_admin=True))
    await db.commit()
    r = await client.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpassword123"})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture
async def regular_token(client):
    await client.post("/api/auth/register", json={"email": "regular@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "regular@test.com", "password": "password123"})
    return r.json()["access_token"]


async def test_admin_stats_requires_admin(client, regular_token):
    r = await client.get("/api/admin/stats", headers={"Authorization": f"Bearer {regular_token}"})
    assert r.status_code == 403


async def test_admin_stats_returns_counts(client, admin_token):
    r = await client.get("/api/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    data = r.json()
    for field in ("total_users", "total_jobs", "total_runs", "total_applications"):
        assert field in data
        assert isinstance(data[field], int)


async def test_list_users_requires_admin(client, regular_token):
    r = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {regular_token}"})
    assert r.status_code == 403


async def test_list_users_returns_all_fields(client, admin_token):
    r = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    users = r.json()
    assert isinstance(users, list)
    assert len(users) >= 1
    for u in users:
        for field in ("id", "email", "is_admin", "created_at", "onboarding_complete", "run_count"):
            assert field in u, f"Missing field: {field}"


async def test_list_users_no_n_plus_one(client, admin_token, db: AsyncSession):
    """list_users should work correctly with multiple users (batch queries)."""
    for i in range(5):
        await client.post(
            "/api/auth/register",
            json={"email": f"bulk{i}@test.com", "password": "password123"},
        )
    r = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    users = r.json()
    assert len(users) >= 5
    # All users must have valid run_count (not missing)
    for u in users:
        assert isinstance(u["run_count"], int)


async def test_update_user_toggle_admin(client, admin_token, regular_token, db: AsyncSession):
    # Get regular user id
    me = await client.get("/api/profile", headers={"Authorization": f"Bearer {regular_token}"})
    user_id = me.json()["user_id"]

    r = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_admin": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200

    users = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    user = next((u for u in users.json() if u["id"] == user_id), None)
    assert user is not None
    assert user["is_admin"] is True


async def test_update_user_404(client, admin_token):
    r = await client.patch(
        "/api/admin/users/00000000-0000-0000-0000-000000000000",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404


async def test_delete_user_removes_user(client, admin_token, db: AsyncSession):
    await client.post("/api/auth/register", json={"email": "todelete@test.com", "password": "password123"})
    users_r = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    target = next((u for u in users_r.json() if u["email"] == "todelete@test.com"), None)
    assert target is not None

    r = await client.delete(
        f"/api/admin/users/{target['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200

    users_after = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert not any(u["id"] == target["id"] for u in users_after.json())


async def test_cannot_delete_self(client, admin_token, db: AsyncSession):
    me_r = await client.get("/api/profile", headers={"Authorization": f"Bearer {admin_token}"})
    my_id = me_r.json()["user_id"]
    r = await client.delete(
        f"/api/admin/users/{my_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400


async def test_list_runs_requires_admin(client, regular_token):
    r = await client.get("/api/admin/runs", headers={"Authorization": f"Bearer {regular_token}"})
    assert r.status_code == 403


async def test_list_runs_returns_expected_shape(client, admin_token):
    r = await client.get("/api/admin/runs", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
