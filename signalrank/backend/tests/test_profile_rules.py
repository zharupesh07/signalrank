import pytest

from batch.context import load_base_config

pytestmark = pytest.mark.unit
from domain.profile_rules import (
    build_profile_positive_terms,
    build_profile_title_rules,
    enrich_config_with_profile_rules,
    infer_profile_archetypes,
    profile_description_alignment_multiplier,
    refine_profile_roles_for_ranking,
    text_matches_profile_positive_terms,
    title_rule_flags,
)


def test_infer_profile_archetypes_for_ai_platform_resume():
    cfg = load_base_config()
    resume_text = (
        "Built GenAI agents with Python, AWS, Kubernetes, Docker, Terraform, "
        "RAG, LLM pipelines, MLOps, and platform engineering."
    )
    roles = ["AI Platform Engineer", "MLOps/Platform Engineer"]
    archetypes = infer_profile_archetypes(resume_text, roles, cfg)
    assert "ai_builder" in archetypes
    assert "platform_infra" in archetypes


def test_infer_profile_archetypes_for_example_like_resume_is_not_enterprise_apps_or_data_engineer():
    cfg = load_base_config()
    resume_text = (
        "Senior AI Platform Engineer focused on cloud-native infrastructure, IDP, "
        "MLOps, agentic systems, OIDC, RBAC, GCP, AWS, Kubernetes, Terraform, "
        "LangGraph, MLflow, and CI/CD for enterprise AI systems."
    )
    roles = ["AI Platform Engineer", "MLOps Engineer", "Machine Learning Engineer"]
    archetypes = infer_profile_archetypes(resume_text, roles, cfg)
    assert "ai_builder" in archetypes
    assert "platform_infra" in archetypes
    assert "enterprise_apps" not in archetypes
    assert "data_engineer" not in archetypes


def test_infer_profile_archetypes_for_data_erp_resume():
    cfg = load_base_config()
    resume_text = (
        "Built ETL pipelines with Spark, Airflow, Kafka, SAP and ERP integrations "
        "using Go and Python."
    )
    roles = ["Data Engineer"]
    archetypes = infer_profile_archetypes(resume_text, roles, cfg)
    assert "data_engineer" in archetypes
    assert "enterprise_apps" in archetypes
    assert "ai_builder" not in archetypes


def test_sap_functional_resume_does_not_trigger_ai_builder_from_noisy_terms():
    cfg = load_base_config()
    resume_text = (
        "SAP Certified Application Associate with 7 years of SAP SD consulting, "
        "S/4HANA implementation, OTC process design, MM integration, GTS, ABAP, "
        "and business requirement workshops."
    )
    roles = ["SAP SD Functional Consultant"]
    archetypes = infer_profile_archetypes(resume_text, roles, cfg)
    assert "enterprise_apps" in archetypes
    assert "sap_functional" in archetypes
    assert "sap_sd" in archetypes
    assert "ai_builder" not in archetypes


def test_ai_builder_title_rules_penalize_customer_engineer():
    rules = build_profile_title_rules(["ai_builder"])
    cfg = {"ranking": {"profile_title_rules": rules}}
    flags = title_rule_flags("Customer Engineer, Generative AI", cfg)
    assert flags["strong"] is True


def test_data_engineer_title_rules_do_not_penalize_data_engineer_as_adjacent():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text="Data engineering with Spark, Airflow, SQL, Kafka and ETL.",
        profile_roles=["Data Engineer"],
    )
    flags = title_rule_flags("Senior Data Engineer", enriched)
    assert flags["adjacent"] is False


def test_ai_builder_title_rules_penalize_sap_and_test_automation_when_not_enterprise_apps():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Built agentic AI platforms with AWS, GCP, Kubernetes, Terraform, "
            "MLflow, LangGraph, CI/CD, OIDC, and RBAC."
        ),
        profile_roles=["AI Platform Engineer", "MLOps Engineer"],
    )
    sap_flags = title_rule_flags("Senior Developer/ Development Expert (ABAP), SAP Globalization", enriched)
    qa_flags = title_rule_flags("Senior Software Test Automation - Veeva AI", enriched)
    assert sap_flags["strong"] is True
    assert qa_flags["strong"] is True


def test_sap_functional_title_rules_penalize_basis_btp_and_ai_titles():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "SAP SD consultant with S/4HANA OTC, pricing, order management, "
            "GTS integration, and functional workshops."
        ),
        profile_roles=["SAP SD Consultant"],
    )
    basis_flags = title_rule_flags("SAP Basis Consultant", enriched)
    btp_flags = title_rule_flags("SAP BTP AI Project consultant", enriched)
    sd_flags = title_rule_flags("SAP SD Functional Analyst", enriched)
    p2p_flags = title_rule_flags("Experienced SAP Consultant (S/4 HANA) - Procure to Pay (P2P)", enriched)
    qa_flags = title_rule_flags("Salesforce QA", enriched)
    linux_flags = title_rule_flags("IT Technology Services Senior Specialist - Linux SM, Pacemaker", enriched)
    assert basis_flags["strong"] is True
    assert btp_flags["strong"] is True
    assert p2p_flags["strong"] is True
    assert qa_flags["strong"] is True
    assert linux_flags["strong"] is True
    assert sd_flags["strong"] is False


def test_sap_sd_positive_terms_require_sd_otc_signals():
    terms = build_profile_positive_terms(["sap_sd"])
    assert isinstance(terms, dict)
    assert "sap sd" in terms["core"]
    assert "order to cash" in terms["core"]
    # broad-only terms must NOT be in core
    assert "functional consultant" not in terms["core"]
    assert "functional consultant" in terms["broad"]

    cfg = {"ranking": {"profile_positive_terms": terms}}
    # core match → pass
    assert text_matches_profile_positive_terms(
        "SAP SD Functional Analyst with OTC process ownership",
        cfg,
    ) is True
    # no core match, broad only ("functional consultant") → fail
    assert text_matches_profile_positive_terms(
        "Functional Consultant for Finance processes",
        cfg,
    ) is False
    # no match at all → fail
    assert text_matches_profile_positive_terms(
        "SAP Basis Consultant for Linux administration",
        cfg,
    ) is False


def test_ai_platform_profile_alignment_prefers_platform_ai_jobs_over_pure_research_jobs():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Senior AI Platform Engineer building agentic systems, MLOps, Kubernetes, "
            "Terraform, CI/CD, OIDC, RBAC, and cloud-native AI infrastructure."
        ),
        profile_roles=["AI Platform Engineer", "MLOps Engineer"],
    )

    platform_job = profile_description_alignment_multiplier(
        "Senior AI Platform Engineer",
        "Build MLOps, Kubernetes, CI/CD, and AI infrastructure for LLM systems.",
        enriched,
    )
    research_job = profile_description_alignment_multiplier(
        "Applied Scientist",
        "Train recommendation and personalization models for experimentation and research.",
        enriched,
    )

    assert platform_job > 1.0
    assert research_job < 1.0


def test_refine_profile_roles_for_ranking_prunes_generic_roles_for_ai_platform_resume():
    refined = refine_profile_roles_for_ranking(
        ["AI Engineer", "Data Scientist", "Software Engineer", "AI Platform Engineer"],
        resume_text=(
            "Senior AI Platform Engineer focused on MLOps, IDP, Kubernetes, Terraform, "
            "CI/CD, and cloud-native AI infrastructure."
        ),
        archetypes=["ai_builder", "platform_infra"],
    )

    assert refined[:3] == ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"]
    assert "Data Scientist" not in refined
    assert "Software Engineer" not in refined


def test_infer_profile_archetypes_for_innovation_resume():
    cfg = load_base_config()
    resume_text = (
        "Innovation and R&D consultant focused on emerging technologies, IoT, robotics, "
        "rapid POCs, MVPs, workshop facilitation, and GTM experiments."
    )
    roles = ["Innovation Engineer", "Emerging Technologies Engineer"]
    archetypes = infer_profile_archetypes(resume_text, roles, cfg)
    assert "innovation_rd_engineer" in archetypes


def test_innovation_positive_terms_filter_generic_ai_job_text():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Innovation and R&D consultant focused on emerging technologies, IoT, robotics, "
            "rapid POCs, MVPs, workshop facilitation, and GTM experiments."
        ),
        profile_roles=["Innovation Engineer", "Emerging Technologies Engineer"],
    )
    assert text_matches_profile_positive_terms(
        "Innovation lead for rapid prototyping, PoCs, IoT systems, workshop facilitation",
        enriched,
    ) is True
    assert text_matches_profile_positive_terms(
        "Senior Software Engineer Python GenAI with backend APIs and RAG pipelines",
        enriched,
    ) is False
    assert text_matches_profile_positive_terms(
        "Platform Engineer driving cloud services and delivery systems",
        enriched,
    ) is False


def test_refine_profile_roles_for_ranking_prunes_generic_roles_for_innovation_resume():
    refined = refine_profile_roles_for_ranking(
        ["Innovation Engineer", "Software Engineer", "AI Engineer"],
        resume_text=(
            "Innovation and R&D consultant focused on emerging technologies, IoT, robotics, "
            "rapid POCs, MVPs, workshop facilitation, and GTM experiments."
        ),
        archetypes=["innovation_rd_engineer"],
    )

    assert refined[:3] == ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"]
    assert "Software Engineer" not in refined
    assert "AI Engineer" not in refined


def test_innovation_profile_alignment_penalizes_generic_engineering_titles():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Innovation and R&D consultant focused on emerging technologies, IoT, robotics, "
            "rapid POCs, MVPs, workshop facilitation, and GTM experiments."
        ),
        profile_roles=["Innovation Engineer", "Emerging Technologies Engineer"],
    )

    innovation_job = profile_description_alignment_multiplier(
        "Innovation Lead",
        "Run rapid prototypes, IoT PoCs, workshop facilitation, and GTM experiments.",
        enriched,
    )
    generic_job = profile_description_alignment_multiplier(
        "Senior Software Engineer",
        "Build backend APIs, platform services, and production software systems.",
        enriched,
    )

    assert innovation_job > 1.0
    assert generic_job < 1.0


def test_network_automation_positive_terms_reject_generic_network_titles_without_automation_signals():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Network automation engineer focused on Python tooling, infrastructure automation, "
            "cloud networking, firewall rules, load balancers, and network operations."
        ),
        profile_roles=["Network Automation Engineer", "Infrastructure Automation Engineer"],
    )

    assert text_matches_profile_positive_terms(
        "Network Automation Engineer building cloud network automation with firewalls",
        enriched,
    ) is True
    assert text_matches_profile_positive_terms(
        "Senior Network Engineer for network operations and incident escalation",
        enriched,
    ) is False
    assert text_matches_profile_positive_terms(
        "Platform Engineer for observability, CI/CD, and backend services",
        enriched,
    ) is False


def test_innovation_profile_alignment_penalizes_platform_and_ai_delivery_titles():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Innovation and R&D consultant focused on emerging technologies, IoT, robotics, "
            "rapid POCs, MVPs, workshop facilitation, and GTM experiments."
        ),
        profile_roles=["Innovation Engineer", "Emerging Technologies Engineer"],
    )

    platform_job = profile_description_alignment_multiplier(
        "Platform Engineer",
        "Build cloud platforms, CI/CD pipelines, and infrastructure operations.",
        enriched,
    )
    ai_job = profile_description_alignment_multiplier(
        "AI Engineer",
        "Build LLM pipelines, evaluation workflows, and backend APIs.",
        enriched,
    )

    assert platform_job < 1.0
    assert ai_job < 1.0


def test_network_automation_role_refinement_excludes_generic_ai_and_backend_titles():
    refined = refine_profile_roles_for_ranking(
        ["Network Automation Engineer", "AI Engineer", "Backend Engineer", "Platform Engineer", "Cloud Network Engineer"],
        resume_text=(
            "Network automation engineer focused on Python tooling, infrastructure automation, "
            "cloud networking, firewall rules, load balancers, and network operations."
        ),
        archetypes=["network_automation_engineer"],
    )

    assert refined[:3] == ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"]
    assert "AI Engineer" not in refined
    assert "Backend Engineer" not in refined
    assert "Platform Engineer" not in refined


def test_network_automation_profile_alignment_penalizes_generic_ai_titles():
    cfg = load_base_config()
    enriched = enrich_config_with_profile_rules(
        cfg,
        resume_text=(
            "Network automation engineer focused on Python tooling, infrastructure automation, "
            "cloud networking, firewall rules, load balancers, and network operations."
        ),
        profile_roles=["Network Automation Engineer", "Infrastructure Automation Engineer"],
    )

    network_job = profile_description_alignment_multiplier(
        "Network Automation Engineer",
        "Build network automation, firewall automation, and infrastructure tooling.",
        enriched,
    )
    generic_ai_job = profile_description_alignment_multiplier(
        "AI Engineer",
        "Build model serving, large language model pipelines, and agentic workflows.",
        enriched,
    )

    assert network_job > 1.0
    assert generic_ai_job < 1.0
