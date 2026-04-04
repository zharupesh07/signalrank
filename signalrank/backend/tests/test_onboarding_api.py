import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from api.models import Profile
from api.routes.onboarding import _extract_text_from_pdf
from domain.onboarding_profile import extract_resume_seed_signals, should_run_onboarding_llm


RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"


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
    monkeypatch.setattr(rp, "parse_resume_structure", mock_parse)
    monkeypatch.setattr(rp, "parse_resume_from_images", mock_parse)

    r = await client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.txt", b"Python developer with 3 years experience", "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "questions" in data
    assert len(data["questions"]) >= 3


@pytest.mark.parametrize(
    "pdf_name, expected_role",
    [
        ("ayush_resume_new.pdf", "SAP SD Consultant"),
        ("Example_Candidate_Resume_V2_2.pdf", "AI Platform Engineer"),
        ("Vivek-Gupta-Emerging-Technologies.pdf", "Innovation Engineer"),
        ("aditya.pdf", "Network Automation Engineer"),
    ],
)
async def test_upload_resume_skips_llm_for_high_confidence_fixture_resumes(
    client,
    auth_token,
    monkeypatch,
    pdf_name,
    expected_role,
):
    import llm.resume_parser as rp

    def _should_not_run(*_args, **_kwargs):
        raise AssertionError("LLM parser should not run for high-confidence fixture resumes")

    monkeypatch.setattr(rp, "parse_resume", _should_not_run)
    monkeypatch.setattr(rp, "parse_resume_structure", _should_not_run)
    monkeypatch.setattr(rp, "parse_resume_from_images", _should_not_run)

    resume_text = _extract_text_from_pdf((RESUMES_DIR / pdf_name).read_bytes())

    response = await client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parsing"] is False
    assert payload["extracted"]["recent_titles"]

    profile_response = await client.get(
        "/api/profile",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["candidate_profile"]["confidence_by_field"]["overall"] >= 0.74
    assert profile["role_intent"] == expected_role
    assert expected_role in profile["candidate_profile"]["target_roles_primary"]


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

    profile = await client.get(
        "/api/profile",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert profile.status_code == 200
    assert profile.json()["target_roles"] == ["AI/ML Engineer"]


async def test_upload_resume_prefills_qa_role_and_yoe(client, auth_token, monkeypatch):
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
    signals = extract_resume_seed_signals(parsed)
    assert signals["suggested_roles"] == ["QA Automation Engineer", "Senior Test Engineer"]
    assert signals["skills"] == ["selenium", "python", "playwright"]
    assert should_run_onboarding_llm({"confidence_by_field": {"overall": 0.7}}, parsed) is False


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
