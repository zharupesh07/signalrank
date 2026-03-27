import pytest


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "appuser@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "appuser@test.com", "password": "password123"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


async def test_list_applications_empty(client, auth_token):
    r = await client.get("/api/applications", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    body = r.json()
    # Backend returns paginated wrapper, not a bare array
    assert "applications" in body
    assert body["applications"] == []
    assert body["total"] == 0


async def test_create_and_list_application(client, auth_token):
    r = await client.post(
        "/api/applications",
        json={"company": "Acme", "title": "ML Engineer", "status": "interested"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 201
    app_id = r.json()["id"]

    r = await client.get("/api/applications", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    body = r.json()
    assert "applications" in body
    assert any(a["id"] == app_id for a in body["applications"])
    assert body["total"] >= 1


async def test_list_pagination_shape(client, auth_token):
    """Response must always include applications array + pagination fields."""
    r = await client.get("/api/applications", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    body = r.json()
    for field in ("applications", "total", "page", "limit"):
        assert field in body, f"Missing field: {field}"
    assert isinstance(body["applications"], list)


async def test_update_application_status(client, auth_token):
    r = await client.post(
        "/api/applications",
        json={"company": "Acme2", "title": "SRE", "status": "interested"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    app_id = r.json()["id"]

    r = await client.patch(
        f"/api/applications/{app_id}",
        json={"status": "applied"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200


async def test_delete_application(client, auth_token):
    r = await client.post(
        "/api/applications",
        json={"company": "Del Inc", "title": "Dev", "status": "interested"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    app_id = r.json()["id"]

    r = await client.delete(
        f"/api/applications/{app_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 204


async def test_create_application_invalid_status(client, auth_token):
    r = await client.post(
        "/api/applications",
        json={"company": "Bad", "title": "Dev", "status": "gibberish"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422
