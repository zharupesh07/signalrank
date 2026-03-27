import pytest


@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "onboard@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "onboard@test.com", "password": "password123"})
    return r.json()["access_token"]


async def test_onboarding_status_initial(client, auth_token):
    r = await client.get("/api/onboarding/status", headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200
    assert r.json()["onboarding_complete"] is False
    assert r.json()["has_resume"] is False


async def test_upload_resume_txt(client, auth_token, monkeypatch):
    import llm.resume_parser as rp
    from llm.resume_parser import ResumeParseResult

    async def mock_parse(text, llm_client):
        return ResumeParseResult(skills=["python"], years_of_experience=3)

    monkeypatch.setattr(rp, "parse_resume", mock_parse)

    r = await client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.txt", b"Python developer with 3 years experience", "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "questions" in data
    assert len(data["questions"]) >= 3


async def test_refine_saves_answer(client, auth_token):
    await client.patch(
        "/api/profile",
        json={"role_intent": "ml"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    r = await client.post(
        "/api/onboarding/refine",
        json={"question_id": "target_roles", "answer": ["AI/ML Engineer"]},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "saved"
