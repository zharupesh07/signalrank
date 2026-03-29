from batch.context import load_base_config
from domain.profile_rules import (
    build_profile_positive_terms,
    build_profile_title_rules,
    enrich_config_with_profile_rules,
    infer_profile_archetypes,
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
    assert "sap sd" in terms
    assert "order to cash" in terms

    cfg = {"ranking": {"profile_positive_terms": terms}}
    assert text_matches_profile_positive_terms(
        "SAP SD Functional Analyst with OTC process ownership",
        cfg,
    ) is True
    assert text_matches_profile_positive_terms(
        "SAP Basis Consultant for Linux administration",
        cfg,
    ) is False
