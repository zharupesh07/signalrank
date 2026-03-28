import pytest


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "profuser@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "profuser@test.com", "password": "password123"})
    return r.json()["access_token"]


async def test_get_profile_contains_nested_and_flat_fields(client, auth_token):
    """Profile response must expose fields both at root and under 'profile' key."""
    r = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    data = r.json()

    # Top-level identity fields
    assert "user_id" in data
    assert "email" in data

    # Nested profile object
    assert "profile" in data
    nested = data["profile"]
    for field in ("onboarding_complete", "role_intent", "min_salary"):
        assert field in nested, f"Missing nested field: {field}"

    # Root-level convenience copy of profile fields
    for field in ("onboarding_complete", "role_intent", "min_salary"):
        assert field in data, f"Missing root field: {field}"


async def test_update_profile_persists(client, auth_token):
    r = await client.patch(
        "/api/profile",
        json={"role_intent": "ml_engineer", "min_salary": 120000},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200

    r = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    data = r.json()
    assert data["role_intent"] == "ml_engineer"
    assert data["min_salary"] == 120000
    # Should be consistent between root and nested
    assert data["profile"]["role_intent"] == data["role_intent"]
    assert data["profile"]["min_salary"] == data["min_salary"]


async def test_resume_tailor_nonexistent_job_returns_404(client, auth_token):
    """Tailor endpoint should 404 when job_id does not exist."""
    await client.patch(
        "/api/profile",
        json={"resume_text": "Experienced ML engineer with 5 years of Python."},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "classic"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404


async def test_resume_tailor_invalid_template_returns_422(client, auth_token):
    """Tailor endpoint should 422 for unknown template names."""
    await client.patch(
        "/api/profile",
        json={"resume_text": "Experienced ML engineer with 5 years of Python."},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "invalid-template"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422
