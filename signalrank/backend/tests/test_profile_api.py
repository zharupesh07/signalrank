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
    assert "is_admin" in data

    # Nested profile object
    assert "profile" in data
    nested = data["profile"]
    for field in ("onboarding_complete", "role_intent", "min_salary", "resume_template", "resume_editor"):
        assert field in nested, f"Missing nested field: {field}"

    # Root-level convenience copy of profile fields
    for field in ("onboarding_complete", "role_intent", "min_salary", "resume_template", "resume_editor"):
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
                "email": "example@example.com",
                "phone": "+91 90000 00000",
                "location": "Bengaluru, India",
                "linkedin": "https://linkedin.com/in/example",
                "github": "https://github.com/example",
                "website": "https://example.dev",
                "summary": "Platform engineer with **Python** experience.",
                "experiences": [
                    {
                        "title": "Senior Engineer",
                        "company": "Dow Chemical International Private Limited",
                        "dates": "Jan 2024 - Present",
                        "location": "Bengaluru, India",
                        "bullets": ["Built internal tools", "Reduced latency by 35%"],
                    }
                ],
                "projects": [{"name": "SignalRank", "url": "https://github.com/example/signalrank", "description": "Job search copilot"}],
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
    assert "Dow Chemical International Private Limited" in payload["resume_text"]
    assert payload["resume_editor"]["experiences"][0]["company"] == "Dow Chemical International Private Limited"
    assert payload["resume_editor"]["email"] == "example@example.com"
    assert payload["resume_editor"]["certifications"] == ["AWS Certified Developer"]


async def test_get_profile_derives_resume_editor_from_resume_text_without_certifications(client, auth_token):
    resume_text = """Ayush Khandelwal
Senior Information Technology Analyst
Dynamic SAP and enterprise systems consultant with 7 years of experience across SD and MM implementations.
helloayushkh@gmail.com
+91 9044781514
Kanpur, India
linkedin.com/in/ayushhkhandelwal

WORK EXPERIENCE
Senior Information Technology Analyst
Dow Chemical International Private Limited
09/2022 - Present
Mumbai, Maharashtra
Configured delivery processing, shipping point, and storage location determination.
Led issue resolution with business stakeholders and functional teams.

SKILLS AND ABILITIES
SAP SD
SAP MM
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

    assert payload["name"] == "Ayush Khandelwal"
    assert payload["email"] == "helloayushkh@gmail.com"
    assert payload["summary"].startswith("Dynamic SAP and enterprise systems consultant")
    assert payload["experiences"][0]["company"] == "Dow Chemical International Private Limited"
    assert payload["experiences"][0]["bullets"] == [
        "Configured delivery processing, shipping point, and storage location determination.",
        "Led issue resolution with business stakeholders and functional teams.",
    ]
    assert payload["skills"][0]["items"] == ["SAP SD", "SAP MM", "Python"]
    assert payload["certifications"] == []


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
