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


async def test_upload_resume_prefills_qa_role_and_yoe(client, auth_token, monkeypatch):
    import api.routes.onboarding as onboarding_route
    from api.models import Profile
    from llm.resume_parser import ResumeParseResult

    parsed = ResumeParseResult(
        skills=["selenium", "python", "playwright"],
        years_of_experience=6,
        recent_titles=["QA Automation Engineer", "Senior Test Engineer"],
        suggested_roles=["QA / Test Engineer"],
        suggested_locations=["Pune"],
        salary_lpa=18,
        suggested_exclusions=["Support"],
    )
    profile = Profile(user_id="qa-test-user")

    distilled = onboarding_route._apply_parsed_profile_updates(profile, parsed)

    assert profile.target_roles == ["QA / Test Engineer"]
    assert profile.role_intent == "QA / Test Engineer"
    assert profile.min_yoe == 4
    assert profile.max_yoe == 8
    assert profile.target_lpa == 18.0
    assert profile.config_overrides["profile_intent"]["roles"] == ["QA / Test Engineer"]
    assert profile.config_overrides["scraping"]["locations"] == ["Pune"]
    assert profile.config_overrides["title_blocklist"] == ["Support"]
    assert "Experience: 6 years" in distilled


def test_apply_parsed_profile_updates_overwrites_stale_roles_and_locations():
    import api.routes.onboarding as onboarding_route
    from api.models import Profile
    from llm.resume_parser import ResumeParseResult

    profile = Profile(
        user_id="sap-user",
        target_roles=["AI/ML Engineer", "Research Scientist"],
        preferred_locations=["Bangalore"],
        role_intent="AI/ML Engineer",
        config_overrides={
            "profile_intent": {"roles": ["AI/ML Engineer"]},
            "scraping": {"locations": ["Bangalore"]},
            "title_blocklist": ["Support"],
        },
        target_lpa=42.0,
        min_yoe=2,
        max_yoe=5,
    )
    parsed = ResumeParseResult(
        skills=["sap sd", "s/4hana", "otc"],
        years_of_experience=9,
        recent_titles=["SAP SD Consultant"],
        suggested_roles=["SAP SD Consultant"],
        suggested_locations=["Hyderabad"],
        salary_lpa=28,
        suggested_exclusions=["QA Engineer"],
    )

    onboarding_route._apply_parsed_profile_updates(profile, parsed)

    assert profile.target_roles == ["SAP SD Consultant"]
    assert profile.role_intent == "SAP SD Consultant"
    assert profile.preferred_locations == ["Hyderabad"]
    assert profile.config_overrides["profile_intent"]["roles"] == ["SAP SD Consultant"]
    assert profile.config_overrides["scraping"]["locations"] == ["Hyderabad"]
    assert profile.config_overrides["title_blocklist"] == ["QA Engineer"]
    assert profile.target_lpa == 28.0
    assert profile.min_yoe == 7
    assert profile.max_yoe == 11


async def test_refine_preferred_locations_syncs_profile_field(client, auth_token):
    await client.patch(
        "/api/profile",
        json={"role_intent": "sap"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    response = await client.post(
        "/api/onboarding/refine",
        json={"question_id": "preferred_locations", "answer": ["Hyderabad", "Remote only"]},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200

    profile = await client.get(
        "/api/profile",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert profile.status_code == 200
    assert profile.json()["preferred_locations"] == ["Hyderabad", "Remote only"]


async def test_profile_patch_merges_config_overrides_instead_of_replacing(client, auth_token):
    initial = await client.patch(
        "/api/profile",
        json={
            "config_overrides": {
                "profile_intent": {"roles": ["SAP SD Consultant"]},
                "scraping": {"locations": ["Hyderabad"]},
            }
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert initial.status_code == 200

    follow_up = await client.patch(
        "/api/profile",
        json={"config_overrides": {"title_blocklist": ["QA Engineer"]}},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert follow_up.status_code == 200

    profile = await client.get(
        "/api/profile",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    payload = profile.json()
    assert payload["config_overrides"]["profile_intent"]["roles"] == ["SAP SD Consultant"]
    assert payload["config_overrides"]["scraping"]["locations"] == ["Hyderabad"]
    assert payload["config_overrides"]["title_blocklist"] == ["QA Engineer"]
