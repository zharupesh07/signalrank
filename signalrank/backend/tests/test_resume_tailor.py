import pytest


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "tailor@test.com", "password": "pass"})
    r = await client.post("/api/auth/login", json={"email": "tailor@test.com", "password": "pass"})
    return r.json()["access_token"]


async def test_list_templates(client, auth_token):
    r = await client.get("/api/resume/templates", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    assert "templates" in r.json()
    assert "classic" in r.json()["templates"]


async def test_tailor_no_resume_returns_404(client, auth_token):
    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "classic"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 404


async def test_tailor_invalid_template(client, auth_token, monkeypatch):
    import llm.resume_parser as rp
    from llm.resume_parser import ResumeParseResult

    async def mock_parse(text, llm_client):
        return ResumeParseResult(skills=["python"], years_of_experience=2)

    monkeypatch.setattr(rp, "parse_resume", mock_parse)

    await client.post(
        "/api/onboarding/resume",
        files={"file": ("r.txt", b"Python dev", "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    r = await client.post(
        "/api/resume/tailor",
        json={"job_id": "00000000-0000-0000-0000-000000000000", "template": "badtemplate"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422
