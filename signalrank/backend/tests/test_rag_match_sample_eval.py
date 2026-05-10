from __future__ import annotations

import pytest

from tools import hybrid_match_eval
from tools import build_curated_profile_gold
from tools import build_profile_eval_sets
from tools import rag_match_sample_eval as script


def _chunks() -> list[script.EvidenceChunk]:
    resume = """
    Senior AI Platform Engineer building LLMOps systems, RAG workflows, and agentic AI tools.
    Python, FastAPI, Docker, Kubernetes, AWS, GCP, CI/CD, PyTorch, and TensorFlow.
    """
    profile = {
        "target_roles_primary": ["AI Platform Engineer", "LLMOps Engineer"],
        "target_roles_adjacent": ["Machine Learning Engineer", "Platform Engineer"],
        "must_have_skills": ["python", "docker", "kubernetes", "aws", "gcp"],
        "good_to_have_skills": ["RAG", "Agentic AI"],
        "domains": ["AI / ML", "Platform / Infrastructure"],
    }
    return script._resume_chunks(resume, profile)


def _profile() -> dict:
    return {
        "target_roles_primary": ["AI Platform Engineer", "LLMOps Engineer"],
        "target_roles_adjacent": ["Machine Learning Engineer", "Platform Engineer"],
        "must_have_skills": ["python", "docker", "kubernetes", "aws", "gcp"],
        "good_to_have_skills": ["RAG", "Agentic AI"],
        "domains": ["AI / ML", "Platform / Infrastructure"],
        "preferred_locations": ["Remote only", "Bangalore"],
    }


def _resume() -> str:
    return """
    Senior AI Platform Engineer building LLMOps systems, RAG workflows, and agentic AI tools.
    Python, FastAPI, Docker, Kubernetes, AWS, GCP, CI/CD, PyTorch, and TensorFlow.
    """


def _strong_factors() -> script.MatchFactors:
    return script.MatchFactors(
        role_score=100.0,
        evidence_score=100.0,
        skill_score=100.0,
        semantic_score=100.0,
        location_score=100.0,
        constraint_score=100.0,
        final_score=100.0,
        band="strong_fit",
        hard_constraints=[],
    )


def _strong_simple_score() -> hybrid_match_eval.SimpleScore:
    return hybrid_match_eval.SimpleScore(
        score=95.0,
        band="strong_fit",
        gate_failed=False,
        gate_reasons=[],
    )


def _eval_job(title: str, description: str = "") -> hybrid_match_eval.EvalJob:
    return hybrid_match_eval.EvalJob(
        label="reject",
        label_reason="test",
        current_score=80.0,
        current_fit_band="moderate",
        title=title,
        company="Example",
        location="Remote",
        job_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        description=description
        or "Build Python, AWS, GCP, LLM, RAG, and Kubernetes systems.",
    )


def test_ai_ml_job_scores_as_strong_fit():
    job = script.SampleJob(
        expected="good",
        current_score=85.0,
        current_fit_band="moderate",
        title="Machine Learning Engineer",
        company="Example",
        location="Remote",
        job_url="https://example.com/ml",
        description="Build Python services for machine learning, LLM, RAG, Docker, Kubernetes, AWS, and GCP.",
    )

    results = script.evaluate_requirements(script.extract_requirements(job), _chunks())
    score, band = script.synthesize_score(results)

    assert band == "strong_fit"
    assert score >= 75


def test_hybrid_ai_ml_job_scores_as_strong_fit():
    job = script.SampleJob(
        expected="good",
        current_score=85.0,
        current_fit_band="moderate",
        title="Machine Learning Engineer",
        company="Example",
        location="Remote",
        job_url="https://example.com/ml",
        description="Build Python services for machine learning, LLM, RAG, Docker, Kubernetes, AWS, and GCP.",
    )
    requirements = script.extract_requirements(job)
    chunks = script._resume_chunks(_resume(), _profile())
    results = script.evaluate_requirements(requirements, chunks)

    factors = script.synthesize_hybrid_score(
        requirements, results, chunks, _resume(), _profile(), job
    )

    assert factors.band == "strong_fit"
    assert factors.final_score >= 75
    assert factors.skill_score >= 70
    assert factors.hard_constraints == []


def test_project_manager_title_caps_incidental_ai_keyword_overlap():
    job = script.SampleJob(
        expected="bad",
        current_score=0.0,
        current_fit_band=None,
        title="Project Manager",
        company="Example",
        location="Remote",
        job_url="https://example.com/pm",
        description="Manage AI/ML delivery with AWS, GCP, PyTorch, TensorFlow, and stakeholder reporting.",
    )

    results = script.evaluate_requirements(script.extract_requirements(job), _chunks())
    score, band = script.synthesize_score(results)

    assert band == "reject"
    assert score <= 34


def test_hybrid_project_manager_title_caps_incidental_ai_keyword_overlap():
    job = script.SampleJob(
        expected="bad",
        current_score=0.0,
        current_fit_band=None,
        title="Project Manager",
        company="Example",
        location="Remote",
        job_url="https://example.com/pm",
        description="Manage AI/ML delivery with AWS, GCP, PyTorch, TensorFlow, and stakeholder reporting.",
    )
    requirements = script.extract_requirements(job)
    chunks = script._resume_chunks(_resume(), _profile())
    results = script.evaluate_requirements(requirements, chunks)

    factors = script.synthesize_hybrid_score(
        requirements, results, chunks, _resume(), _profile(), job
    )

    assert factors.band == "reject"
    assert factors.final_score <= 34
    assert factors.hard_constraints == [
        "title_lane_mismatch:Project / Program Management"
    ]


def test_skill_graph_gives_related_skill_credit():
    job = script.SampleJob(
        expected="good",
        current_score=80.0,
        current_fit_band="moderate",
        title="RAG Engineer",
        company="Example",
        location="Remote",
        job_url="https://example.com/rag",
        description="Build retrieval augmented generation systems with vector databases.",
    )

    score = script._skill_graph_score(
        script.extract_requirements(job),
        "Built LLM and agentic AI systems with LangChain.",
        {"must_have_skills": ["LLM", "Agentic AI", "LangChain"]},
        job,
    )

    assert score > 0


def test_unknown_engineer_lane_does_not_get_full_role_credit():
    job = script.SampleJob(
        expected="bad",
        current_score=70.0,
        current_fit_band="moderate",
        title="ETL Engineer",
        company="Example",
        location="Remote",
        job_url="https://example.com/etl",
        description="Build Python ETL pipelines with AWS and SQL.",
    )
    requirements = script.extract_requirements(job)
    chunks = script._resume_chunks(_resume(), _profile())
    results = script.evaluate_requirements(requirements, chunks)

    factors = script.synthesize_hybrid_score(
        requirements, results, chunks, _resume(), _profile(), job
    )

    assert factors.band == "reject"
    assert factors.final_score <= 34
    assert factors.hard_constraints


def test_simplified_score_gates_data_pipeline_without_ai_context():
    job = hybrid_match_eval.EvalJob(
        label="reject",
        label_reason="test",
        current_score=80.0,
        current_fit_band="moderate",
        title="ETL Engineer",
        company="Example",
        location="Remote",
        job_url="https://example.com/etl",
        description="Build data pipelines with Python, SQL, and AWS.",
    )
    score = hybrid_match_eval._simplified_score(
        _strong_factors(), job=job, current_score=job.current_score
    )

    assert score.band == "reject"
    assert score.score <= 34
    assert score.gate_reasons == ["data_pipeline_without_ai_platform_context"]


@pytest.mark.parametrize(
    "title,description",
    [
        ("Zero Trust Network Engineer", "Build zero trust networking platforms."),
        ("UX Design Engineer - AI & Agentic Systems", "Design AI UX workflows."),
        ("IN-Senior Associate_MERN Developer_GCC_Advisory", "Build MERN apps."),
        ("Associate, Application Engineer", "Build application services."),
        (
            "Senior Software Engineer in Test - Agentic AI",
            "Build test automation for agentic AI products.",
        ),
        ("Mgr, Software Engineer", "Manage software engineers."),
        ("Principal Engineer", "Lead generic product engineering teams."),
        ("Data Engineer I, Intl. Seller Growth", "Build seller growth data pipelines."),
    ],
)
def test_simplified_score_gates_known_false_positive_lanes(
    title: str, description: str
):
    job = _eval_job(title, description)

    score = hybrid_match_eval._simplified_score(
        _strong_factors(), job=job, current_score=job.current_score
    )

    assert score.band == "reject"
    assert score.score <= 34
    assert score.gate_failed


def test_simplified_score_caps_adjacent_role_below_strong_fit():
    job = _eval_job(
        "Senior Software Engineer",
        "Build backend services with Python, AWS, and Kubernetes.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(), job=job, current_score=job.current_score
    )

    assert score.band == "adjacent_fit"
    assert score.score == 74.9


def test_profile_policy_allows_network_role_for_network_profile():
    profile = {
        "target_roles_primary": ["Network Automation Engineer"],
        "target_roles_adjacent": ["Cloud Network Engineer"],
        "negative_roles": ["Machine Learning Engineer"],
        "must_have_skills": ["Network Automation", "Firewall", "ServiceNow"],
        "domains": ["Network / Infrastructure Automation"],
    }
    job = _eval_job(
        "Zero Trust Network Engineer",
        "Automate firewall, routing, and network infrastructure workflows.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=job.current_score,
        candidate_profile=profile,
    )

    assert score.band == "strong_fit"
    assert score.gate_reasons == []


def test_profile_policy_rejects_ai_role_for_network_profile():
    profile = {
        "target_roles_primary": ["Network Automation Engineer"],
        "negative_roles": ["Machine Learning Engineer"],
        "must_have_skills": ["Network Automation", "Firewall", "ServiceNow"],
        "domains": ["Network / Infrastructure Automation"],
    }
    job = _eval_job(
        "Machine Learning Engineer",
        "Build ML models, RAG systems, and MLOps pipelines.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=job.current_score,
        candidate_profile=profile,
    )

    assert score.band == "reject"
    assert score.score <= 34
    assert score.gate_failed


def test_profile_policy_allows_sap_and_rejects_ai_for_sap_profile():
    profile = {
        "target_roles_primary": ["SAP SD Consultant"],
        "target_roles_adjacent": ["SAP Functional Consultant"],
        "negative_roles": ["Machine Learning Engineer"],
        "must_have_skills": ["SAP SD", "SAP MM", "SAP GTS", "SAP S/4HANA"],
        "domains": ["SAP / ERP"],
    }
    sap_job = _eval_job(
        "SAP SD Consultant",
        "Configure SAP SD, order to cash, S/4HANA, and pricing workflows.",
    )
    ai_job = _eval_job(
        "AI Engineer",
        "Build GenAI, LLM, and MLOps applications.",
    )

    sap_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=sap_job,
        current_score=sap_job.current_score,
        candidate_profile=profile,
    )
    ai_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=ai_job,
        current_score=ai_job.current_score,
        candidate_profile=profile,
    )

    assert sap_score.band == "strong_fit"
    assert sap_score.score >= 76.0
    assert sap_score.gate_reasons == []
    assert ai_score.band == "reject"
    assert ai_score.score <= 34


def test_sap_policy_does_not_promote_generic_otc_without_sap_evidence():
    profile = {
        "target_roles_primary": ["SAP SD Consultant"],
        "target_roles_adjacent": ["Senior Systems Engineer"],
        "negative_roles": ["Machine Learning Engineer"],
        "must_have_skills": ["SAP SD", "SAP MM", "SAP GTS", "SAP S/4HANA"],
        "domains": ["SAP / ERP"],
    }
    otc_job = _eval_job(
        "OTC Consultant",
        "Own order to cash process work with business stakeholders.",
    )
    systems_job = _eval_job(
        "Senior Systems Engineer",
        "Support enterprise network systems and customer troubleshooting.",
    )

    otc_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=otc_job,
        current_score=otc_job.current_score,
        candidate_profile=profile,
    )
    systems_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=systems_job,
        current_score=systems_job.current_score,
        candidate_profile=profile,
    )

    assert otc_score.band == "weak_fit"
    assert otc_score.score <= 49.9
    assert "sap_context_title_without_sap_evidence" in otc_score.gate_reasons
    assert systems_score.band == "weak_fit"
    assert systems_score.score <= 49.9
    assert "sap_adjacent_title_without_sap_evidence" in systems_score.gate_reasons


def test_sap_curated_label_rejects_generic_otc_and_keeps_sap_titles_strong():
    profile, _resume_text = build_profile_eval_sets.build_profile("ayush")
    policy = hybrid_match_eval._build_match_policy(profile)
    otc_job = {
        "title": "OTC Consultant",
        "description": "Own order to cash process work with business stakeholders.",
    }
    sap_job = {
        "title": "SAP SD Consultant",
        "description": "Configure SAP SD and S/4HANA order to cash workflows.",
    }

    otc_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=_eval_job(otc_job["title"], otc_job["description"]),
        current_score=90.0,
        match_policy=policy,
    )
    sap_score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=_eval_job(sap_job["title"], sap_job["description"]),
        current_score=90.0,
        match_policy=policy,
    )

    assert (
        build_curated_profile_gold._label_job(
            otc_job,
            score=otc_score,
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "reject"
    )
    assert (
        build_curated_profile_gold._label_job(
            sap_job,
            score=sap_score,
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "strong_pursue"
    )


def test_sap_policy_scores_generic_functional_consultant_as_weak_adjacent():
    profile, _resume_text = build_profile_eval_sets.build_profile("ayush")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Functional Consultant L1",
        "Support functional consulting workflows for enterprise customers.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "weak_fit"
    assert 50.0 <= score.score <= 54.9
    assert score.gate_reasons == []


def test_profile_policy_allows_full_stack_when_profile_targets_it():
    profile = {
        "target_roles_primary": ["Full Stack Developer"],
        "target_roles_adjacent": ["Software Engineer"],
        "negative_roles": ["Sales Engineer", "Support Engineer"],
        "must_have_skills": ["Node.js", "React", "Python", "Postgres"],
        "domains": ["Backend / Product Engineering"],
    }
    job = _eval_job(
        "Senior Full Stack Developer",
        "Build React, Node.js, Python, and Postgres product features.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=job.current_score,
        candidate_profile=profile,
    )

    assert score.band == "strong_fit"
    assert score.gate_reasons == []


def test_build_profile_eval_sets_derives_sap_policy_for_ayush():
    profile, _resume_text = build_profile_eval_sets.build_profile("ayush")
    policy = hybrid_match_eval._build_match_policy(profile)

    assert "sap_erp" in policy.active_lanes
    assert any("SAP" in role for role in profile["target_roles_primary"])
    assert "sap sd consultant" in policy.direct_title_terms


def test_build_profile_eval_sets_derives_network_policy_for_aditya():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)

    assert "network_automation" in policy.active_lanes
    assert "backend_product" not in policy.active_lanes
    assert "qa_automation" not in policy.active_lanes
    assert "network engineer" in policy.direct_title_terms


def test_network_policy_rejects_backend_cloud_network_product_role():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Senior Software Engineer (Backend, Cloud Network Management)",
        "Build backend services for cloud network management products.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "reject"
    assert score.score <= 34
    assert "non_target_engineering_lane" in score.gate_reasons


def test_vivek_policy_does_not_promote_generic_backend_software_role():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Senior Software Engineer-Backend",
        "Build backend services for enterprise incident management workflows.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "weak_fit"
    assert score.score <= 54.9
    assert "generic_or_unknown_lane" in score.gate_reasons


def test_body_only_domain_context_does_not_make_generic_software_role_direct():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Senior Software Engineer",
        "Build backend services that support conversational AI workflows.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "weak_fit"
    assert score.score <= 54.9


def test_direct_policy_title_gets_generic_score_floor():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Network Engineer",
        "Troubleshoot routing, switching, and firewall issues.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=10.0,
        match_policy=policy,
    )

    assert score.score >= 62.0


def test_network_policy_caps_plain_network_ops_below_strong_fit():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Network Engineer",
        "Troubleshoot routing, switching, firewall, DNS, DHCP, and production outages.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "adjacent_fit"
    assert score.score <= 74.9


def test_network_policy_scores_direct_automation_evidence_as_strong():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Network Engineer",
        "Automate network operations with Python, Ansible, routing, and switching.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "strong_fit"
    assert score.score >= 76.0


def test_network_policy_caps_adjacent_infra_without_network_automation_evidence():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Linux / Nginx Infrastructure Engineer",
        "Migrate IIS applications to Ubuntu and Nginx with Python deployment scripts.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "weak_fit"
    assert score.score <= 54.9
    assert "network_adjacent_title_without_direct_network_role" in score.gate_reasons


def test_network_curated_label_requires_automation_evidence_for_strong():
    profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    policy = hybrid_match_eval._build_match_policy(profile)
    plain_job = {
        "title": "Network Engineer",
        "description": "Troubleshoot routing, switching, firewall, DNS, and DHCP.",
    }
    automation_job = {
        "title": "Network Engineer",
        "description": "Automate network operations with Python, Bash, and Ansible.",
    }

    assert (
        build_curated_profile_gold._label_job(
            plain_job,
            score=_strong_simple_score(),
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "maybe_adjacent"
    )
    assert (
        build_curated_profile_gold._label_job(
            automation_job,
            score=_strong_simple_score(),
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "strong_pursue"
    )


def test_vivek_policy_caps_generic_r_and_d_without_specific_solution_evidence():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "R&D Engineer 3",
        "Build advanced software for high speed network test products with C++ and Python.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "weak_fit"
    assert score.score <= 54.9
    assert "generic_emerging_title_without_solution_evidence" in score.gate_reasons


def test_vivek_policy_scores_specific_emerging_tech_as_strong():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Creative Technologist",
        "Build Firefly creative workflows, POCs, and GenAI prototypes.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "strong_fit"
    assert score.score >= 76.0


def test_vivek_policy_keeps_generic_prototyping_cloud_architect_adjacent():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    job = _eval_job(
        "Senior Prototyping Architect , Prototyping And Cloud Engineering (PACE)",
        "Lead AWS cloud prototyping work with customers and delivery teams.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(),
        job=job,
        current_score=90.0,
        match_policy=policy,
    )

    assert score.band == "adjacent_fit"
    assert score.score <= 74.9


def test_vivek_curated_label_downgrades_generic_ai_and_keeps_specific_roles_strong():
    profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    policy = hybrid_match_eval._build_match_policy(profile)
    generic_job = {
        "title": "Senior AI Developer",
        "description": "Build GenAI applications with Python, cloud APIs, and analytics.",
    }
    creative_job = {
        "title": "Creative Technologist",
        "description": "Build Firefly creative workflows, POCs, and GenAI prototypes.",
    }
    conversational_job = {
        "title": "Consultant | Conversational AI",
        "description": "Build chatbot and voice AI solutions using NLP and LLMs.",
    }

    assert (
        build_curated_profile_gold._label_job(
            generic_job,
            score=_strong_simple_score(),
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "maybe_adjacent"
    )
    assert (
        build_curated_profile_gold._label_job(
            creative_job,
            score=_strong_simple_score(),
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "strong_pursue"
    )
    assert (
        build_curated_profile_gold._label_job(
            conversational_job,
            score=_strong_simple_score(),
            factors=_strong_factors(),
            policy=policy,
        )[0]
        == "strong_pursue"
    )


def test_curated_scrape_terms_are_profile_policy_driven():
    aditya_profile, _resume_text = build_profile_eval_sets.build_profile("aditya")
    aditya_policy = hybrid_match_eval._build_match_policy(aditya_profile)
    vivek_profile, _resume_text = build_profile_eval_sets.build_profile("vivek")
    vivek_policy = hybrid_match_eval._build_match_policy(vivek_profile)

    aditya_terms = build_curated_profile_gold.build_scrape_terms(
        aditya_profile, aditya_policy
    )
    vivek_terms = build_curated_profile_gold.build_scrape_terms(
        vivek_profile, vivek_policy
    )

    assert any("network" in term.lower() for term in aditya_terms)
    assert any(
        "iot" in term.lower() or "innovation" in term.lower() for term in vivek_terms
    )
    assert "python" not in {term.lower() for term in aditya_terms}


def test_cto_title_is_hard_negative():
    job = _eval_job(
        "CTO - Lead of AI/ML Engineer",
        "Lead AI engineering strategy and manage delivery.",
    )

    score = hybrid_match_eval._simplified_score(
        _strong_factors(), job=job, current_score=90.0
    )

    assert score.band == "reject"
    assert score.score <= 34
    assert "hard_negative_title_lane" in score.gate_reasons


def test_balanced_rows_prefers_requested_label_mix():
    rows = []
    for index, label in enumerate(
        ["strong_pursue"] * 5
        + ["maybe_adjacent"] * 5
        + ["reject"] * 5
        + ["hard_violation"] * 5
    ):
        rows.append(
            {
                "job_url": f"https://example.com/{index}",
                "label": label,
                "simplified_score": 100 - index,
            }
        )

    selected = build_profile_eval_sets._balanced_rows(rows, 12)
    counts = {
        label: sum(1 for row in selected if row["label"] == label)
        for label in {row["label"] for row in selected}
    }

    assert counts["strong_pursue"] == 3
    assert counts["maybe_adjacent"] == 3
    assert counts["reject"] == 4
    assert counts["hard_violation"] == 2


def test_eval_metrics_include_ndcg_and_promoted_bad_diagnostics():
    rows = [
        {
            "label": "reject",
            "current_score": 95.0,
            "current_band": "strong_fit",
            "simplified_score": 34.0,
            "simplified_band": "reject",
            "title": "Zero Trust Network Engineer",
            "company": "Example",
        },
        {
            "label": "hard_violation",
            "current_score": 90.0,
            "current_band": "strong_fit",
            "simplified_score": 34.0,
            "simplified_band": "reject",
            "title": "Senior Software Engineer in Test",
            "company": "Example",
        },
        {
            "label": "strong_pursue",
            "current_score": 60.0,
            "current_band": "adjacent_fit",
            "simplified_score": 95.0,
            "simplified_band": "strong_fit",
            "title": "AI Platform Engineer",
            "company": "Example",
        },
        {
            "label": "maybe_adjacent",
            "current_score": 55.0,
            "current_band": "adjacent_fit",
            "simplified_score": 74.9,
            "simplified_band": "adjacent_fit",
            "title": "Senior Software Engineer",
            "company": "Example",
        },
    ]

    current = hybrid_match_eval._score_metrics(
        rows, score_key="current_score", band_key="current_band", top_k=4
    )
    simplified = hybrid_match_eval._score_metrics(
        rows, score_key="simplified_score", band_key="simplified_band", top_k=4
    )

    assert (
        simplified["pairwise_preference_accuracy"]
        > current["pairwise_preference_accuracy"]
    )
    assert simplified["ndcg_at_25"] > current["ndcg_at_25"]
    assert current["promoted_bad"]
    assert simplified["promoted_bad"] == []


def test_redacts_email_and_phone_from_evidence_chunks():
    chunks = script._resume_chunks(
        "Candidate\nEmail example@example.com\nPhone +91 98765 43210\nBuilt RAG systems with Python.",
        {},
    )

    combined = " ".join(chunk.text for chunk in chunks)

    assert "example@example.com" not in combined
    assert "98765" not in combined
    assert "Built RAG systems" in combined
