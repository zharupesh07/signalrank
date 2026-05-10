import pytest
import pandas as pd
from types import SimpleNamespace

from tools import hybrid_match_eval as hybrid
from batch.ranker import _apply_intent_shadow_matching
from domain.intent_matching import (
    JOB_INTENT_KEY,
    MATCH_DECISION_KEY,
    build_job_intent,
    build_profile_intent,
    extract_intent_with_llm,
    merge_llm_intent,
    needs_llm_fallback,
    score_intent_match,
)


def _profile(
    *,
    target_roles: list[str],
    adjacent_roles: list[str] | None = None,
    negative_roles: list[str] | None = None,
    skills: list[str] | None = None,
    domains: list[str] | None = None,
    seniority: str = "senior",
):
    return build_profile_intent(
        {
            "target_roles_primary": target_roles,
            "target_roles_adjacent": adjacent_roles or [],
            "negative_roles": negative_roles or [],
            "must_have_skills": skills or [],
            "good_to_have_skills": [],
            "domains": domains or [],
            "seniority_band": seniority,
        },
        resume_text=" ".join([*target_roles, *(skills or []), *(domains or [])]),
    )


def _job(title: str, description: str, *, skills: list[str] | None = None):
    return build_job_intent(
        title=title,
        company="Example",
        description=description,
        job_profile={
            "required_skills": skills or [],
            "preferred_skills": [],
        },
    )


def _score_metrics(rows: list[dict], *, top_k: int = 10) -> dict:
    return hybrid._score_metrics(
        rows,
        score_key="intent_score",
        band_key="intent_band",
        top_k=top_k,
    )


@pytest.mark.parametrize(
    ("profile", "job_intent"),
    [
        (
            _profile(
                target_roles=["Cybersecurity Engineer"],
                skills=["zero trust", "iam", "siem"],
                domains=["cybersecurity"],
            ),
            _job(
                "Zero Trust Security Engineer",
                "Own ZTNA, IAM, SIEM integrations and vulnerability remediation.",
                skills=["zero trust", "iam", "siem"],
            ),
        ),
        (
            _profile(
                target_roles=["Frontend Engineer"],
                skills=["react", "typescript", "frontend"],
                domains=["frontend"],
            ),
            _job(
                "Senior Frontend Engineer",
                "Build React web applications and TypeScript component systems.",
                skills=["react", "typescript"],
            ),
        ),
        (
            _profile(
                target_roles=["Data Analyst"],
                skills=["sql", "tableau", "analytics"],
                domains=["data analytics"],
            ),
            _job(
                "Data Analyst",
                "Create SQL dashboards, Tableau reporting, and business analytics.",
                skills=["sql", "tableau"],
            ),
        ),
        (
            _profile(
                target_roles=["Embedded Mechanical Engineer"],
                skills=["firmware", "sensors", "mechanical"],
                domains=["embedded mechanical"],
            ),
            _job(
                "Embedded Mechanical Engineer",
                "Build firmware for sensors and mechanical hardware prototypes.",
                skills=["firmware", "sensors"],
            ),
        ),
        (
            _profile(
                target_roles=["SAP Consultant"],
                skills=["sap", "s/4hana", "abap"],
                domains=["sap erp"],
            ),
            _job(
                "SAP S/4HANA Consultant",
                "Implement SAP ERP workflows with ABAP extensions.",
                skills=["sap", "s/4hana", "abap"],
            ),
        ),
        (
            _profile(
                target_roles=["Network Automation Engineer"],
                skills=["network automation", "servicenow", "firewall"],
                domains=["network automation"],
            ),
            _job(
                "Network Automation Engineer",
                "Automate firewalls, routing workflows, and ServiceNow remediation.",
                skills=["network automation", "servicenow", "firewall"],
            ),
        ),
        (
            _profile(
                target_roles=["AI Platform Engineer"],
                skills=["mlops", "llmops", "model serving"],
                domains=["ai platform"],
            ),
            _job(
                "Senior AI Platform Engineer",
                "Run MLOps, LLMOps, model serving, and production AI systems.",
                skills=["mlops", "llmops", "model serving"],
            ),
        ),
        (
            _profile(
                target_roles=["Creative Technologist"],
                skills=["iot", "computer vision", "conversational ai"],
                domains=["emerging technologies"],
            ),
            _job(
                "Creative Technologist",
                "Prototype IoT, computer vision, and conversational AI experiences.",
                skills=["iot", "computer vision", "conversational ai"],
            ),
        ),
    ],
)
def test_unseen_profile_direct_intents_score_strong(profile, job_intent):
    decision = score_intent_match(profile, job_intent, current_score=60)

    assert decision["band"] == "strong_fit"
    assert decision["hard_constraints"] == []


def test_synthetic_cross_profile_eval_gates_are_profile_agnostic():
    profiles = [
        _profile(
            target_roles=["Cybersecurity Engineer"],
            skills=["zero trust", "iam", "siem"],
            domains=["cybersecurity"],
        ),
        _profile(
            target_roles=["Product Manager"],
            skills=["roadmap", "product strategy", "analytics"],
            domains=["product management"],
            seniority="mid",
        ),
        _profile(
            target_roles=["Frontend Engineer"],
            skills=["react", "typescript", "frontend"],
            domains=["frontend"],
        ),
        _profile(
            target_roles=["Data Analyst"],
            skills=["sql", "tableau", "analytics"],
            domains=["data analytics"],
        ),
        _profile(
            target_roles=["Network Automation Engineer"],
            skills=["network automation", "servicenow", "firewall"],
            domains=["network automation"],
        ),
        _profile(
            target_roles=["SAP Consultant"],
            skills=["sap", "s/4hana", "abap"],
            domains=["sap erp"],
        ),
        _profile(
            target_roles=["AI Platform Engineer"],
            skills=["mlops", "llmops", "model serving"],
            domains=["ai platform"],
        ),
        _profile(
            target_roles=["Creative Technologist"],
            skills=["iot", "computer vision", "conversational ai"],
            domains=["emerging technologies"],
        ),
    ]
    matching_jobs = [
        _job(
            "Zero Trust Security Engineer",
            "Own ZTNA, IAM, SIEM integrations and vulnerability remediation.",
            skills=["zero trust", "iam", "siem"],
        ),
        _job(
            "Product Manager",
            "Own product roadmap, product strategy, analytics, and discovery.",
            skills=["roadmap", "product strategy", "analytics"],
        ),
        _job(
            "Senior Frontend Engineer",
            "Build React web applications and TypeScript component systems.",
            skills=["react", "typescript"],
        ),
        _job(
            "Data Analyst",
            "Create SQL dashboards, Tableau reporting, and analytics.",
            skills=["sql", "tableau"],
        ),
        _job(
            "Network Automation Engineer",
            "Automate firewalls, routing workflows, and ServiceNow remediation.",
            skills=["network automation", "servicenow", "firewall"],
        ),
        _job(
            "SAP S/4HANA Consultant",
            "Implement SAP ERP workflows with ABAP extensions.",
            skills=["sap", "s/4hana", "abap"],
        ),
        _job(
            "Senior AI Platform Engineer",
            "Run MLOps, LLMOps, model serving, and production AI systems.",
            skills=["mlops", "llmops", "model serving"],
        ),
        _job(
            "Creative Technologist",
            "Prototype IoT, computer vision, and conversational AI experiences.",
            skills=["iot", "computer vision", "conversational ai"],
        ),
    ]
    hard_negative_jobs = [
        _job(
            "QA Automation Engineer", "Own product test automation.", skills=["python"]
        ),
        _job("Account Executive", "Own enterprise sales pipeline.", skills=["crm"]),
        _job(
            "Technical Support Engineer",
            "Support customer incidents.",
            skills=["cloud"],
        ),
        _job("Engineering Manager", "Manage engineers and hiring.", skills=["roadmap"]),
        _job(
            "Associate Application Engineer",
            "Entry-level support role.",
            skills=["java"],
        ),
    ]
    generic_bad_jobs = [
        _job("Widget Orchestration Specialist", "Coordinate stakeholder updates."),
        _job("Generic Software Engineer", "Build internal tools.", skills=["java"]),
        _job("Data Engineer", "Own ETL pipelines.", skills=["spark"]),
    ]

    for profile, matching_job in zip(profiles, matching_jobs):
        rows: list[dict] = []
        for job, label in [
            (matching_job, "strong_pursue"),
            *[(job, "hard_violation") for job in hard_negative_jobs],
            *[(job, "reject") for job in generic_bad_jobs],
        ]:
            decision = score_intent_match(profile, job, current_score=92)
            stable_key = f"{id(profile)}-{label}-{len(rows)}"
            rows.append(
                {
                    "label": label,
                    "intent_score": decision["score"],
                    "intent_band": decision["band"],
                    "title": (job.get("role_titles") or [""])[0],
                    "company": "Example",
                    "job_url": stable_key,
                    "hard_constraints": decision["hard_constraints"],
                }
            )

        metrics = _score_metrics(rows, top_k=1)
        assert metrics["top_jobs"][0]["label"] == "strong_pursue"
        assert metrics["hard_violation_at_k"] == 0
        assert metrics["rejects_promoted_at_k"] == 0
        assert metrics["ndcg_at_10"] >= 0.9
        for row in rows:
            if row["label"] == "hard_violation":
                assert row["intent_score"] <= 34
            if row["label"] in {"hard_violation", "reject"}:
                assert row["intent_band"] not in {"strong_fit", "adjacent_fit"}


def test_product_manager_is_not_people_manager_negative():
    profile = _profile(
        target_roles=["Product Manager"],
        skills=["roadmap", "product strategy", "analytics"],
        domains=["product management"],
        seniority="mid",
    )
    product_job = _job(
        "Product Manager",
        "Own product roadmap, product strategy, analytics, and customer discovery.",
        skills=["roadmap", "product strategy", "analytics"],
    )
    engineering_manager_job = _job(
        "Engineering Manager",
        "Manage engineers, hiring, performance reviews, and delivery.",
        skills=["roadmap"],
    )

    product_decision = score_intent_match(profile, product_job, current_score=50)
    manager_decision = score_intent_match(
        profile,
        engineering_manager_job,
        current_score=95,
    )

    assert product_decision["band"] == "strong_fit"
    assert manager_decision["score"] <= 34
    assert manager_decision["hard_constraints"]


@pytest.mark.parametrize(
    "title",
    [
        "QA Automation Engineer",
        "SDET Agentic AI",
        "Account Executive",
        "Technical Support Engineer",
        "Associate Application Engineer",
    ],
)
def test_hard_negative_roles_are_capped(title):
    profile = _profile(
        target_roles=["AI Platform Engineer"],
        negative_roles=["QA Engineer", "Sales", "Support"],
        skills=["mlops", "python", "agentic ai"],
        domains=["ai platform"],
    )
    job = _job(
        title,
        "Work on agentic AI products with Python and MLOps.",
        skills=["python", "mlops"],
    )

    decision = score_intent_match(profile, job, current_score=98)

    assert decision["score"] <= 34
    assert decision["band"] == "reject"


def test_unknown_role_family_stays_below_strong_without_direct_evidence():
    profile = _profile(
        target_roles=["Operations Specialist"],
        skills=["jira", "process improvement"],
        domains=["operations process"],
        seniority="mid",
    )
    job = _job(
        "Widget Orchestration Specialist",
        "Coordinate process work, Jira queues, and stakeholder updates.",
        skills=["jira"],
    )

    decision = score_intent_match(profile, job, current_score=96)

    assert needs_llm_fallback(profile)
    assert decision["band"] != "strong_fit"
    assert decision["score"] < 75


def test_llm_schema_merge_cannot_bypass_deterministic_hard_gates():
    profile = _profile(
        target_roles=["AI Platform Engineer"],
        skills=["mlops", "python", "agentic ai"],
        domains=["ai platform"],
    )
    job = build_job_intent(
        title="SDET Agentic AI",
        description="Build test automation for agentic AI products.",
        job_profile={"required_skills": ["python", "mlops"]},
        llm_intent={
            "role_family": "ai_platform",
            "role_titles": ["AI Platform Engineer"],
            "required_skills": ["python", "mlops"],
            "confidence": 0.95,
        },
    )

    decision = score_intent_match(profile, job, current_score=98)

    assert "qa_test" in job["hard_constraints"]
    assert decision["score"] <= 34
    assert decision["band"] == "reject"


@pytest.mark.asyncio
async def test_llm_fallback_disabled_or_failed_keeps_deterministic_intent():
    class FailedClient:
        async def llm_json(self, **kwargs):
            return {"_error": "llm_failed"}

    base = _profile(target_roles=["Mystery Specialist"], skills=["unknown"])
    merged = await extract_intent_with_llm(
        llm_client=FailedClient(),
        kind="profile",
        text="Mystery Specialist",
        base_intent=base,
    )

    assert merged == base


def test_llm_merge_preserves_base_hard_constraints():
    base = _job(
        "Technical Support Engineer",
        "Support customers with cloud incidents.",
        skills=["cloud"],
    )
    merged = merge_llm_intent(
        base,
        {
            "role_family": "ai_platform",
            "hard_constraints": [],
            "confidence": 0.95,
        },
        expected_kind="job",
    )

    assert "support" in merged["hard_constraints"]
    assert merged["role_family"] == "ai_platform"


@pytest.mark.asyncio
async def test_intent_shadow_does_not_modify_live_final_score():
    profile_intent = _profile(
        target_roles=["Network Automation Engineer"],
        skills=["network automation", "servicenow"],
        domains=["network automation"],
    )
    job_intent = _job(
        "Network Automation Engineer",
        "Automate ServiceNow network remediation.",
        skills=["network automation", "servicenow"],
    )
    df = pd.DataFrame(
        [
            {
                "id": "job-1",
                "title": "Network Automation Engineer",
                "company": "Example",
                "description": "Automate ServiceNow network remediation.",
                "location": "Remote",
                "site": "test",
                "date_posted": None,
                "role_clusters": [],
                "job_profile": {JOB_INTENT_KEY: job_intent},
                "final_score": 71.5,
                "match_report": {"verdict": "strong_fit"},
            }
        ]
    )

    result = await _apply_intent_shadow_matching(
        df,
        cfg={"ranking": {"intent_matching": {"shadow_enabled": True}}},
        resume_text="network automation servicenow",
        profile=SimpleNamespace(
            candidate_profile={"profile_intent_v1": profile_intent}
        ),
        db=SimpleNamespace(),
    )

    assert result.at[0, "final_score"] == 71.5
    assert result.at[0, "intent_shadow_band"] == "strong_fit"
    assert MATCH_DECISION_KEY in result.at[0, "match_report"]
