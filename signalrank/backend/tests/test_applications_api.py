import pytest
from sqlalchemy import select

from api.models import Application, JobRaw, JobResult, Run, User


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


async def test_import_from_run_normalizes_scores_and_respects_fraction_threshold(client, auth_token, db):
    user_result = await db.execute(select(User).where(User.email == "appuser@test.com"))
    user = user_result.scalar_one()

    run = Run(user_id=user.id, status="success")
    db.add(run)
    await db.flush()

    low_job = JobRaw(job_url="https://example.com/jobs/low", title="Low Score", company="Acme")
    high_job = JobRaw(job_url="https://example.com/jobs/high", title="High Score", company="Beta")
    db.add_all([low_job, high_job])
    await db.flush()

    db.add_all(
        [
            JobResult(
                run_id=run.id,
                user_id=user.id,
                job_id=low_job.id,
                final_score=58.0,
                semantic_score=0.41,
            ),
            JobResult(
                run_id=run.id,
                user_id=user.id,
                job_id=high_job.id,
                final_score=75.16,
                semantic_score=0.67,
            ),
        ]
    )
    await db.commit()

    response = await client.post(
        "/api/applications/import-from-run",
        json={"run_id": run.id, "min_score": 0.7, "limit": 20},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"created": 1, "skipped": 0}

    apps_response = await client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert apps_response.status_code == 200
    apps = apps_response.json()["applications"]
    assert len(apps) == 1
    assert apps[0]["company"] == "Beta"
    assert apps[0]["system_score"] == pytest.approx(0.7516)
    assert apps[0]["resume_match_pct"] == pytest.approx(0.67)


async def test_list_applications_normalizes_legacy_percent_scores(client, auth_token, db):
    user_result = await db.execute(select(User).where(User.email == "appuser@test.com"))
    user = user_result.scalar_one()

    legacy_app = Application(
        user_id=user.id,
        company="LegacyCo",
        title="Engineer",
        status="interested",
        system_score=75.16,
        resume_match_pct=82.0,
    )
    db.add(legacy_app)
    await db.commit()

    response = await client.get(
        "/api/applications",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    app = next(a for a in response.json()["applications"] if a["id"] == legacy_app.id)
    assert app["system_score"] == pytest.approx(0.7516)
    assert app["resume_match_pct"] == pytest.approx(0.82)
