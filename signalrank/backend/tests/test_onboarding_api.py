import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Profile


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


async def test_onboarding_parsed_completes_when_parse_status_is_done_even_without_skills(client, auth_token):
    await client.patch(
        "/api/profile",
        json={
            "resume_text": "Experienced backend engineer",
            "config_overrides": {
                "onboarding": {"parse_status": "done"},
                "profile_intent": {"roles": ["Backend Engineer"]},
                "scraping": {"locations": ["Pune"]},
            },
            "target_lpa": 24,
            "min_yoe": 4,
            "max_yoe": 8,
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )

    response = await client.get(
        "/api/onboarding/parsed",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parsing"] is False
    assert payload["prefill"]["target_roles"] == ["Backend Engineer"]
    assert payload["prefill"]["preferred_locations"] == ["Pune"]
    assert payload["prefill"]["career_intent"] == {}


async def test_onboarding_parsed_returns_empty_prefill_when_parse_failed(
    client,
    auth_token,
    db: AsyncSession,
):
    await client.patch(
        "/api/profile",
        json={
            "resume_text": "Uploaded resume text",
            "config_overrides": {
                "onboarding": {"parse_status": "failed"},
                "profile_intent": {"roles": ["Stale Role"]},
            },
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    profile = (
        await db.execute(select(Profile).where(Profile.user_id.is_not(None)))
    ).scalar_one()
    profile.skills = ["stale-skill"]
    await db.commit()

    response = await client.get(
        "/api/onboarding/parsed",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"parsing": False, "prefill": {}}


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
    assert profile.config_overrides["career_intent"]["target_roles"][0]["title"] == "QA / Test Engineer"
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
    assert "QA Automation" in profile.config_overrides["title_blocklist"]
    assert profile.config_overrides["career_intent"]["target_roles"][0]["title"] == "SAP SD Consultant"
    assert "SAP S/4HANA SD Consultant" in profile.custom_search_queries
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
