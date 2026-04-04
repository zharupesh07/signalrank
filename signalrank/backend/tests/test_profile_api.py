from unittest.mock import patch

import pytest
from sqlalchemy import select

from api.models import Profile, User


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
    assert "is_admin" in data

    # Nested profile object
    assert "profile" in data
    nested = data["profile"]
    for field in ("onboarding_complete", "role_intent", "min_salary", "resume_template", "resume_editor", "career_intent", "candidate_profile"):
        assert field in nested, f"Missing nested field: {field}"

    # Root-level convenience copy of profile fields
    for field in ("onboarding_complete", "role_intent", "min_salary", "resume_template", "resume_editor", "career_intent", "candidate_profile"):
        assert field in data, f"Missing root field: {field}"


async def test_update_profile_persists(client, auth_token):
    r = await client.patch(
        "/api/profile",
        json={"role_intent": "ml_engineer", "min_salary": 120000, "config_overrides": {"resume": {"template": "modern"}}},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200

    r = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    data = r.json()
    assert data["role_intent"] == "ml_engineer"
    assert data["min_salary"] == 120000
    assert data["resume_template"] == "modern"
    # Should be consistent between root and nested
    assert data["profile"]["role_intent"] == data["role_intent"]
    assert data["profile"]["min_salary"] == data["min_salary"]
    assert data["profile"]["resume_template"] == data["resume_template"]


async def test_update_profile_resume_editor_updates_resume_text_and_roundtrips(client, auth_token):
    response = await client.patch(
        "/api/profile",
        json={
            "resume_editor": {
                "name": "Example Candidate",
                "position": "Senior Software Engineer",
                "email": "candidate@example.com",
                "phone": "+91 90000 00000",
                "location": "Remote",
                "linkedin": "https://linkedin.com/in/example-candidate",
                "github": "https://github.com/example-candidate",
                "website": "https://candidate.dev",
                "summary": "Platform engineer with **Python** experience.",
                "experiences": [
                    {
                        "title": "Senior Engineer",
                        "company": "Example Enterprise",
                        "dates": "Jan 2024 - Present",
                        "location": "Remote",
                        "bullets": ["Built internal tools", "Reduced latency by 35%"],
                    }
                ],
                "projects": [{"name": "Example Project", "url": "https://github.com/example-candidate/example-project", "description": "Job search copilot"}],
                "skills": [{"category": "Programming", "items": ["Python", "SQL"]}],
                "certifications": ["AWS Certified Developer"],
            }
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200

    response = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    payload = response.json()
    assert "Example Enterprise" in payload["resume_text"]
    assert payload["resume_editor"]["experiences"][0]["company"] == "Example Enterprise"
    assert payload["resume_editor"]["email"] == "candidate@example.com"
    assert payload["resume_editor"]["certifications"] == ["AWS Certified Developer"]


async def test_get_profile_derives_resume_editor_from_resume_text_without_certifications(client, auth_token):
    resume_text = """Example Candidate
Senior Technology Analyst
Dynamic enterprise systems consultant with 7 years of experience across delivery and process implementations.
candidate@example.com
+91 9044781514
Remote
linkedin.com/in/example-candidate

WORK EXPERIENCE
Senior Technology Analyst
Example Enterprise
09/2022 - Present
Remote
Configured delivery processing, shipping point, and storage location determination.
Led issue resolution with business stakeholders and functional teams.

SKILLS AND ABILITIES
ERP Delivery
Process Design
Python
"""

    response = await client.patch(
        "/api/profile",
        json={"resume_text": resume_text},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200

    response = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    payload = response.json()["resume_editor"]

    assert payload["name"] == "Example Candidate"
    assert payload["email"] == "candidate@example.com"
    assert payload["summary"].startswith("Dynamic enterprise systems consultant")
    assert payload["experiences"][0]["company"] == "Example Enterprise"
    assert payload["experiences"][0]["bullets"] == [
        "Configured delivery processing, shipping point, and storage location determination.",
        "Led issue resolution with business stakeholders and functional teams.",
    ]
    assert payload["skills"][0]["items"] == ["ERP Delivery", "Process Design", "Python"]
    assert payload["certifications"] == []


async def test_get_profile_prefers_stored_resume_editor_without_reparsing(client, auth_token):
    response = await client.patch(
        "/api/profile",
        json={
            "resume_editor": {
                "name": "Stored Candidate",
                "position": "Senior Platform Engineer",
                "email": "stored@example.com",
                "phone": "+91 90000 00000",
                "location": "Remote",
                "linkedin": "https://linkedin.com/in/stored-candidate",
                "github": "https://github.com/stored-candidate",
                "website": "https://stored.dev",
                "summary": "Stored summary.",
                "experiences": [
                    {
                        "title": "Senior Engineer",
                        "company": "Stored Enterprise",
                        "dates": "2024 - Present",
                        "location": "Remote",
                        "bullets": ["Built systems"],
                    }
                ],
                "projects": [],
                "skills": [{"category": "General", "items": ["Python"]}],
                "certifications": ["Stored Cert"],
            }
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200

    with patch("api.routes.profile.parse_resume_editor") as mock_parse:
        response = await client.get("/api/profile", headers={"Authorization": f"Bearer {auth_token}"})

    assert response.status_code == 200
    payload = response.json()["resume_editor"]
    assert payload["name"] == "Stored Candidate"
    assert payload["github"] == "https://github.com/stored-candidate"
    mock_parse.assert_not_called()


async def test_update_profile_resume_editor_rejects_invalid_email(client, auth_token):
    response = await client.patch(
        "/api/profile",
        json={
            "resume_editor": {
                "email": "not-an-email",
                "experiences": [],
                "projects": [],
                "skills": [],
            }
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 422


async def test_update_profile_accepts_contact_handles_without_scheme(client, auth_token):
    response = await client.patch(
        "/api/profile",
        json={
            "resume_editor": {
                "name": "Example Candidate",
                "linkedin": "linkedin.com/in/example-candidate",
                "github": "github.com/example-candidate",
                "website": "example.dev",
            }
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200


async def test_admin_refresh_profiles_rebuilds_resume_editor(client, db):
    await client.post("/api/auth/register", json={"email": "refresh@test.com", "password": "password123"})
    user = (await db.execute(select(User).where(User.email == "refresh@test.com"))).scalar_one()
    user.is_admin = True
    profile = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    profile.resume_text = "Example Candidate\nSoftware Engineer\nGitHub: github.com/examplecandidate\n"
    profile.config_overrides = {"resume_editor": {"name": "Example Candidate", "github": ""}}
    await db.commit()

    token = (await client.post("/api/auth/login", json={"email": "refresh@test.com", "password": "password123"})).json()["access_token"]
    response = await client.post(
        "/api/onboarding/profiles/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    refreshed = (await client.get("/api/profile", headers={"Authorization": f"Bearer {token}"})).json()
    assert "examplecandidate" in refreshed["resume_editor"]["github"].lower()


async def test_profile_options_exposes_shared_taxonomy(client, auth_token):
    response = await client.get(
        "/api/profile/options",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "role_options" in payload
    assert "canonical_role_options" in payload
    assert "location_options" in payload
    assert "tier_options" in payload
    assert "title_penalty_rules" in payload
    assert "company_tier_lists" in payload
    assert "SAP SD Consultant" in payload["role_options"]
    assert "QA / Test Engineer" in payload["canonical_role_options"]
    assert "Remote only" in payload["location_options"]
    assert "strong" in payload["title_penalty_rules"]
    assert "adjacent" in payload["title_penalty_rules"]
    assert "hybrid" in payload["title_penalty_rules"]
    assert "Atlassian" in payload["company_tier_lists"]["tier_ss"]
    assert "Microsoft" in payload["company_tier_lists"]["tier_s"]


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
