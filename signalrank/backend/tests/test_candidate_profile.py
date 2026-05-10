from llm.resume_parser import ResumeParseResult

from domain.candidate_profile import build_candidate_profile
from domain.intent_matching import PROFILE_INTENT_KEY


def test_build_candidate_profile_uses_resume_intent_and_evidence():
    parsed = ResumeParseResult(
        skills=["Python", "Terraform", "Kubernetes"],
        years_of_experience=8,
        recent_titles=["Senior Platform Engineer", "DevOps Engineer"],
        suggested_roles=["Platform Engineer"],
        suggested_locations=["Remote only", "Bangalore"],
        suggested_exclusions=["QA Engineer"],
        career_archetypes=[{"id": "platform_infra", "label": "Platform Infra"}],
        ambiguities=["Open to hybrid if needed"],
    )

    profile = build_candidate_profile(
        parsed=parsed,
        resume_text="Platform engineer with Kubernetes and Terraform experience. Remote-first.",
        cfg={
            "skills": {
                "equivalence_groups": {
                    "python": {"canonical": "python", "variants": ["python"]},
                    "terraform": {"canonical": "terraform", "variants": ["terraform"]},
                    "kubernetes": {"canonical": "kubernetes", "variants": ["kubernetes"]},
                }
            }
        },
    )

    assert profile["target_roles_primary"] == ["Platform Engineer"]
    assert "Senior Platform Engineer" in profile["target_roles_adjacent"]
    assert profile["negative_roles"] == ["QA Engineer"]
    assert profile["seniority_band"] == "senior"
    assert profile["preferred_locations"] == ["Remote only", "Bangalore"]
    assert "remote" in profile["preferred_work_modes"]
    assert profile["must_have_skills"] == ["kubernetes", "python", "terraform"]
    assert profile["career_archetypes"] == ["platform_infra"]
    assert profile["artifact_version"].startswith("candidate_profile_")
    assert profile["schema_version"] == 1
    assert len(profile["profile_fingerprint"]) == 64
    assert len(profile["profile_cache_key"]) == 64
    assert profile["evidence_snippets"][0]["source"] == "parsed_roles"
    assert profile["ambiguities"] == ["Open to hybrid if needed"]


def test_build_candidate_profile_generalizes_across_unrelated_resumes():
    cases = [
        (
            ResumeParseResult(
                skills=["React", "TypeScript", "GraphQL"],
                years_of_experience=5,
                recent_titles=["Frontend Engineer"],
                suggested_roles=["Frontend Engineer"],
            ),
            "Built React dashboards, design systems, and frontend GraphQL clients.",
            "frontend",
            "Frontend Engineer",
        ),
        (
            ResumeParseResult(
                skills=["Spark", "Airflow", "Databricks"],
                years_of_experience=6,
                recent_titles=["Data Engineer"],
                suggested_roles=["Data Engineer"],
            ),
            "Owned Spark ETL pipelines, Airflow orchestration, and lakehouse data quality.",
            "data_engineering",
            "Data Engineer",
        ),
        (
            ResumeParseResult(
                skills=["Zero Trust", "SIEM", "IAM"],
                years_of_experience=7,
                recent_titles=["Security Engineer"],
                suggested_roles=["Cybersecurity Engineer"],
            ),
            "Implemented zero trust controls, SIEM detections, and IAM governance.",
            "cybersecurity",
            "Cybersecurity Engineer",
        ),
        (
            ResumeParseResult(
                skills=["SDET", "Playwright", "Test Automation"],
                years_of_experience=4,
                recent_titles=["QA Automation Engineer"],
                suggested_roles=["QA Automation Engineer"],
            ),
            "Built Playwright test automation, SDET tooling, and release quality gates.",
            "qa_test",
            "QA Automation Engineer",
        ),
    ]

    for parsed, resume_text, expected_family, expected_role in cases:
        profile = build_candidate_profile(parsed=parsed, resume_text=resume_text)
        intent = profile[PROFILE_INTENT_KEY]

        assert expected_role in profile["target_roles_primary"]
        assert expected_family in intent["role_families"]
        assert "AI Platform Engineer" not in intent["target_roles"]
        assert "Kubernetes" not in intent["must_have_skills"]
        assert "Terraform" not in intent["must_have_skills"]
