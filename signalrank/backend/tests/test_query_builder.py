import pytest
from unittest.mock import MagicMock

from batch.context import load_base_config
from batch.query_builder import (
    build_profile_scan_plan,
    build_query_plan_debug,
    build_queries,
)
from domain.intent_matching import PROFILE_INTENT_KEY, build_profile_intent

pytestmark = pytest.mark.unit


def _mock_profile(**kwargs):
    p = MagicMock()
    p.target_roles = kwargs.get("target_roles")
    p.preferred_locations = kwargs.get("preferred_locations")
    p.custom_search_queries = kwargs.get("custom_search_queries")
    config_overrides = kwargs.get("config_overrides")
    if kwargs.get("legacy", True):
        config_overrides = {
            **(config_overrides or {}),
            "scraping": {
                **((config_overrides or {}).get("scraping") or {}),
                "intent_query_planner": {
                    **(
                        ((config_overrides or {}).get("scraping") or {}).get(
                            "intent_query_planner"
                        )
                        or {}
                    ),
                    "use_for_scrape": False,
                },
            },
        }
    p.config_overrides = config_overrides
    p.candidate_profile = kwargs.get("candidate_profile")
    return p


def _intent_profile(
    *,
    target_roles: list[str],
    role_families: list[str],
    skills: list[str] | None = None,
    adjacent_roles: list[str] | None = None,
    negative_roles: list[str] | None = None,
    confidence: float = 0.86,
    use_for_scrape: bool = False,
):
    candidate_profile = {
        "target_roles_primary": target_roles,
        "target_roles_adjacent": adjacent_roles or [],
        "negative_roles": negative_roles or [],
        "must_have_skills": skills or [],
        "good_to_have_skills": [],
        "domains": role_families,
        "seniority_band": "senior",
    }
    intent = build_profile_intent(
        candidate_profile, resume_text=" ".join(target_roles + (skills or []))
    )
    intent["primary_role_families"] = role_families
    intent["role_families"] = role_families
    intent["confidence"] = confidence
    candidate_profile[PROFILE_INTENT_KEY] = intent
    return _mock_profile(
        target_roles=target_roles,
        preferred_locations=["Pune"],
        custom_search_queries=[],
        candidate_profile=candidate_profile,
        legacy=False,
        config_overrides={
            "scraping": {
                "intent_query_planner": {
                    "shadow_enabled": True,
                    "use_for_scrape": use_for_scrape,
                    "default_max_terms": 8,
                    "default_max_locations": 3,
                }
            }
        },
    )


def test_base_config_enables_intent_query_planner_for_scrape():
    cfg = load_base_config()

    assert cfg["scraping"]["intent_query_planner"]["use_for_scrape"] is True
    assert cfg["ranking"]["intent_matching"]["use_for_final_score"] is False


def test_basic_queries():
    p = _mock_profile(target_roles=["ML Engineer"], preferred_locations=["Bangalore"])
    queries = build_queries(p)
    assert len(queries) == 1
    assert queries[0].term == "ML Engineer"
    assert queries[0].location == "Bangalore"


def test_custom_queries_added():
    p = _mock_profile(
        target_roles=["ML Engineer"],
        preferred_locations=["Pune"],
        custom_search_queries=["LLM Infra"],
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "ML Engineer" in terms
    assert "LLM Infra" in terms


def test_dedup_case_insensitive():
    p = _mock_profile(
        target_roles=["ML Engineer"],
        custom_search_queries=["ml engineer"],
        preferred_locations=["Remote"],
    )
    queries = build_queries(p)
    assert len(queries) == 1


def test_fallback_to_config_overrides():
    p = _mock_profile(
        target_roles=None,
        preferred_locations=None,
        custom_search_queries=None,
        config_overrides={
            "profile_intent": {"roles": ["Data Scientist"]},
            "scraping": {"locations": ["Mumbai"]},
        },
    )
    queries = build_queries(p)
    assert len(queries) == 1
    assert queries[0].term == "Data Scientist"
    assert queries[0].location == "Mumbai"


def test_cap_at_50():
    p = _mock_profile(
        target_roles=[f"Role {i}" for i in range(20)],
        preferred_locations=[f"City {j}" for j in range(10)],
    )
    queries = build_queries(p, max_terms=20)
    assert len(queries) <= 50


def test_default_country_when_no_locations():
    p = _mock_profile(target_roles=["Engineer"], preferred_locations=None)
    queries = build_queries(p)
    assert len(queries) == 1
    # "India" is country-like, normalized to city="" for country-wide jobspy search
    assert queries[0].location == ""
    assert queries[0].country == "India"


def test_role_alias_expands_to_relevant_query_terms():
    p = _mock_profile(
        target_roles=["QA Automation Engineer"], preferred_locations=["Pune"]
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "QA Automation Engineer" in terms
    assert "SDET" in terms
    assert "Test Engineer" in terms


def test_sap_queries_stay_narrow_to_erp_roles():
    p = _mock_profile(
        target_roles=["SAP SD Consultant"], preferred_locations=["Bangalore"]
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "SAP SD Consultant" in terms
    assert "SAP OTC Functional Consultant" in terms
    assert "SAP S/4HANA SD Consultant" in terms
    assert "SAP Consultant" not in terms


def test_career_intent_query_plan_is_included():
    p = _mock_profile(
        target_roles=["Network Automation Engineer"],
        preferred_locations=["Pune"],
        custom_search_queries=[],
        config_overrides={
            "career_intent": {
                "query_plan": {
                    "title_queries": ["Infrastructure Automation Engineer"],
                    "skill_queries": ["Ansible Python Network Automation"],
                    "domain_queries": ["Cloud Networking"],
                    "negative_keywords": ["AI Platform Engineer"],
                }
            }
        },
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "Network Automation Engineer" in terms
    assert "Infrastructure Automation Engineer" in terms
    assert "Ansible Python Network Automation" not in terms
    assert "Cloud Networking" in terms


def test_skill_queries_do_not_become_standalone_scrape_terms():
    p = _mock_profile(
        target_roles=["AI Platform Engineer"],
        preferred_locations=["Pune"],
        custom_search_queries=[],
        config_overrides={
            "career_intent": {
                "query_plan": {
                    "title_queries": ["MLOps Engineer"],
                    "skill_queries": ["Kubernetes", "Terraform", "CI/CD"],
                    "domain_queries": ["AI platform"],
                    "negative_keywords": [],
                }
            }
        },
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "AI Platform Engineer" in terms
    assert "MLOps Engineer" in terms
    assert "AI platform" in terms
    assert "Kubernetes" not in terms
    assert "Terraform" not in terms
    assert "CI/CD" not in terms


def test_negative_keywords_are_filtered_from_queries():
    p = _mock_profile(
        target_roles=[
            "Innovation Engineer",
            "AI Engineer",
            "Network Automation Engineer",
        ],
        preferred_locations=["Pune"],
        custom_search_queries=[],
        config_overrides={
            "career_intent": {
                "query_plan": {
                    "title_queries": ["Innovation Engineer", "AI Platform Engineer"],
                    "skill_queries": ["Kubernetes"],
                    "domain_queries": ["R&D"],
                    "negative_keywords": ["AI", "Platform", "Data Scientist"],
                }
            }
        },
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "Innovation Engineer" in terms
    assert "AI Platform Engineer" not in terms
    assert "AI Engineer" not in terms


def test_shadow_mode_keeps_live_queries_unchanged():
    p = _intent_profile(
        target_roles=["AI Platform Engineer"],
        role_families=["ai_platform"],
        skills=["Kubernetes", "MLOps", "LLMOps"],
        use_for_scrape=False,
    )
    queries = build_queries(p, max_terms=1)
    debug = build_query_plan_debug(p)

    assert [query.term for query in queries] == ["AI Platform Engineer"]
    assert "MLOps Engineer" in debug["intent_terms"]
    assert debug["counts"]["intent_terms"] > len(queries)


def test_use_for_scrape_switches_to_intent_terms():
    p = _intent_profile(
        target_roles=["AI Platform Engineer"],
        role_families=["ai_platform"],
        skills=["Kubernetes", "MLOps", "LLMOps"],
        use_for_scrape=True,
    )
    terms = [query.term for query in build_queries(p)]

    assert "AI Platform Engineer" in terms
    assert "MLOps Engineer" in terms
    assert "Data Scientist" not in terms
    assert len(set(terms)) <= 8


def test_intent_scrape_expands_to_remote_location_without_changing_terms():
    p = _intent_profile(
        target_roles=["AI Platform Engineer"],
        role_families=["ai_platform"],
        skills=["MLOps"],
        use_for_scrape=True,
    )
    queries = build_queries(p, max_terms=1)

    ai_platform_queries = [
        query for query in queries if query.term == "AI Platform Engineer"
    ]

    assert {query.location for query in ai_platform_queries} == {"Pune", ""}


def test_compound_resume_headline_is_normalized_to_search_title():
    p = _intent_profile(
        target_roles=[
            "Senior AI Platform Engineer | Cloud Infrastructure | MLOps | Agentic Systems"
        ],
        role_families=["ai_platform"],
        skills=["MLOps", "LLMOps"],
        use_for_scrape=True,
    )
    terms = [query.term for query in build_queries(p)]

    assert "Senior AI Platform Engineer" in terms
    assert all("|" not in term for term in terms)


def test_certification_headline_does_not_become_intent_query():
    p = _intent_profile(
        target_roles=["SAP Certified Application Associate - SAP S/4HANA Sales"],
        role_families=["sap_erp"],
        skills=["SAP SD", "S/4HANA"],
        use_for_scrape=True,
    )
    terms = [query.term for query in build_queries(p)]

    assert "SAP Certified Application Associate - SAP S/4HANA Sales" not in terms
    assert "SAP SD Consultant" in terms
    assert "SAP OTC Functional Consultant" in terms
    assert "SAP SD Consultant SAP SD" not in terms


def test_cybersecurity_intent_queries_are_not_generic_software():
    p = _intent_profile(
        target_roles=["Cybersecurity Engineer"],
        role_families=["cybersecurity"],
        skills=["zero trust", "IAM", "SIEM"],
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}

    assert "Zero Trust Security Engineer" in terms
    assert "Software Engineer" not in terms


def test_frontend_intent_uses_title_skill_anchors_not_backend():
    p = _intent_profile(
        target_roles=["Frontend Engineer"],
        role_families=["frontend"],
        skills=["React", "TypeScript"],
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}

    assert "Frontend Engineer React" in terms
    assert "React" not in terms
    assert "Backend Engineer" not in terms


def test_network_automation_avoids_generic_devops_platform_terms():
    p = _intent_profile(
        target_roles=["Network Automation Engineer"],
        role_families=["network_automation"],
        skills=["ServiceNow", "firewall", "routing"],
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}

    assert "Network Automation Engineer ServiceNow" in terms
    assert "NetDevOps Engineer" in terms
    assert "Network Automation Engineer network automation" not in terms
    assert "Cloud Network Engineer" in terms
    assert "DevOps Engineer" not in terms
    assert "Platform Engineer" not in terms


def test_emerging_tech_queries_include_specific_applied_ai_titles():
    p = _intent_profile(
        target_roles=["Creative Technologist"],
        role_families=["emerging_tech"],
        skills=["computer vision", "conversational AI", "IoT"],
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}

    assert "Computer Vision AI Architect" in terms
    assert "Conversational AI Architect" in terms


def test_product_manager_does_not_trigger_people_manager_negative():
    p = _intent_profile(
        target_roles=["Product Manager"],
        role_families=["product_management"],
        skills=["roadmap", "product strategy", "analytics"],
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}
    debug = build_query_plan_debug(p)

    assert "Product Manager" in terms
    assert "Product Manager roadmap" in terms
    assert all(
        "Product Manager" != item["term"] for item in debug["rejected_candidates"]
    )


def test_unknown_intent_uses_exact_titles_only():
    p = _intent_profile(
        target_roles=["Widget Orchestration Specialist"],
        role_families=["general"],
        skills=["Python", "Kubernetes"],
        confidence=0.5,
        use_for_scrape=True,
    )
    terms = {query.term for query in build_queries(p)}

    assert terms == {"Widget Orchestration Specialist"}


def test_query_plan_gates_reject_standalone_skills_and_hard_negatives():
    p = _intent_profile(
        target_roles=["AI Platform Engineer"],
        role_families=["ai_platform"],
        skills=["Kubernetes", "Python"],
        use_for_scrape=True,
    )
    debug = build_query_plan_debug(p)

    assert "Kubernetes" not in debug["intent_terms"]
    assert "Python" not in debug["intent_terms"]
    assert all("QA Engineer" != term for term in debug["intent_terms"])
    assert debug["gates"]["passes"] is True


def test_standalone_skill_candidates_are_rejected_when_generated():
    p = _intent_profile(
        target_roles=["Frontend Engineer"],
        role_families=["frontend"],
        skills=["React", "TypeScript"],
        use_for_scrape=True,
    )
    debug = build_query_plan_debug(p)
    rejected = {
        item["term"]: item["risk_flags"] for item in debug["rejected_candidates"]
    }

    assert "React" in rejected
    assert "standalone_skill" in rejected["React"]


def test_query_plan_rejects_entry_level_adjacent_terms_for_senior_profiles():
    p = _intent_profile(
        target_roles=["Network Automation Engineer"],
        adjacent_roles=["IT Trainee", "Network Engineer I"],
        role_families=["network_automation"],
        skills=["ServiceNow", "firewall"],
        use_for_scrape=True,
    )
    debug = build_query_plan_debug(p)
    rejected = {
        item["term"]: item["risk_flags"] for item in debug["rejected_candidates"]
    }

    assert "IT Trainee" not in debug["intent_terms"]
    assert "Network Engineer I" not in debug["intent_terms"]
    assert "entry_level_role" in rejected["Network Engineer I"]


def test_query_plan_rejects_domain_only_terms():
    p = _intent_profile(
        target_roles=["SAP SD Consultant"],
        role_families=["sap_erp"],
        skills=["S/4HANA", "SAP SD"],
        use_for_scrape=True,
    )
    debug = build_query_plan_debug(p)
    rejected = {
        item["term"]: item["risk_flags"] for item in debug["rejected_candidates"]
    }

    assert "S/4HANA" not in debug["intent_terms"]
    assert "domain_only" in rejected["S/4HANA"]


def test_profile_scan_plan_exposes_terms_locations_negatives_and_rejections():
    p = _intent_profile(
        target_roles=["AI Platform Engineer"],
        role_families=["ai_platform"],
        skills=["Kubernetes", "MLOps", "Python"],
        use_for_scrape=True,
    )

    plan = build_profile_scan_plan(p)

    assert plan["version"] == "profile_scan_plan_v1"
    assert plan["use_for_scrape"] is True
    assert "AI Platform Engineer" in plan["search_terms"]
    assert "MLOps Engineer" in plan["workday_search_terms"]
    assert "Pune" in plan["locations"]
    assert "Data Scientist" in plan["title_filter"]["negative"]
    assert plan["confidence"] >= 0.8
    rejected = {item["term"]: item["risk_flags"] for item in plan["rejected_terms"]}
    assert "MLOps" in rejected
    assert "domain_only" in rejected["MLOps"]


def test_generic_adjacent_resume_titles_are_rejected():
    p = _intent_profile(
        target_roles=["SAP SD Consultant"],
        adjacent_roles=[
            "Application Development Analyst",
            "Senior Information Technology Analyst",
            "SAP OTC Functional Consultant",
        ],
        role_families=["sap_erp"],
        skills=["SAP SD", "S/4HANA"],
        use_for_scrape=True,
    )
    debug = build_query_plan_debug(p)
    rejected = {
        item["term"]: item["risk_flags"] for item in debug["rejected_candidates"]
    }

    assert "Application Development Analyst" not in debug["intent_terms"]
    assert "Senior Information Technology Analyst" not in debug["intent_terms"]
    assert "SAP OTC Functional Consultant" in debug["intent_terms"]
    assert "weak_adjacent_title" in rejected["Application Development Analyst"]
