from domain.career_intent import build_career_intent_profile
from llm.resume_parser import ResumeParseResult


def test_build_career_intent_profile_for_sap_resume_adds_negative_qa_targets():
    parsed = ResumeParseResult(
        skills=["SAP SD", "Order to Cash", "Pricing", "Billing"],
        recent_titles=["SAP SD Consultant"],
        years_of_experience=8,
    )

    profile = build_career_intent_profile(parsed)

    titles = [item["title"] for item in profile["target_roles"]]
    negatives = [item["label"] for item in profile["negative_targets"]]
    title_queries = profile["query_plan"]["title_queries"]

    assert "SAP SD Consultant" in titles
    assert "SAP OTC Functional Consultant" in titles
    assert "QA Automation" in negatives
    assert "SAP S/4HANA SD Consultant" in title_queries


def test_build_career_intent_profile_for_network_automation_resume_adds_specific_archetype():
    parsed = ResumeParseResult(
        skills=["Ansible", "Python", "Cloud Networking"],
        recent_titles=["Network Automation Engineer"],
        years_of_experience=6,
    )

    profile = build_career_intent_profile(parsed)

    archetype_ids = [item["id"] for item in profile["career_archetypes"]]
    titles = [item["title"] for item in profile["target_roles"]]
    negatives = profile["query_plan"]["negative_keywords"]

    assert "network_automation_engineer" in archetype_ids
    assert "Network Automation Engineer" in titles
    assert "AI Platform Engineer" in negatives


def test_build_career_intent_profile_for_innovation_resume_preserves_non_generic_track():
    parsed = ResumeParseResult(
        skills=["IoT", "Computer Vision", "Rapid Prototyping"],
        recent_titles=["Innovation Lead"],
        years_of_experience=10,
    )

    profile = build_career_intent_profile(parsed)

    archetype_ids = [item["id"] for item in profile["career_archetypes"]]
    titles = [item["title"] for item in profile["target_roles"]]

    assert "innovation_rd_engineer" in archetype_ids
    assert "Innovation Engineer" in titles
    assert "R&D Engineer" in profile["query_plan"]["title_queries"]


def test_build_career_intent_profile_for_ai_platform_resume_prefers_platform_roles():
    parsed = ResumeParseResult(
        skills=["Python", "GCP", "Kubernetes", "Terraform", "MLOps", "LangGraph"],
        recent_titles=["Senior AI Platform Engineer", "Senior Machine Learning Engineer"],
        suggested_search_queries=["AI Platform Engineer", "Data Scientist"],
        years_of_experience=7,
    )

    profile = build_career_intent_profile(parsed)

    archetype_ids = [item["id"] for item in profile["career_archetypes"]]
    titles = [item["title"] for item in profile["target_roles"]]

    assert "ai_platform_engineer" in archetype_ids
    assert titles[:3] == ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"]
    assert "Data Scientist" not in titles
    assert "AI Platform Engineer" in profile["query_plan"]["title_queries"]
