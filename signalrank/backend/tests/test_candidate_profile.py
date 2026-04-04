from llm.resume_parser import ResumeParseResult

from domain.candidate_profile import build_candidate_profile


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
