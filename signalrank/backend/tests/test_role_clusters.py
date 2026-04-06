import pytest

from domain.role_clusters import infer_clusters_from_job_text, roles_to_clusters

pytestmark = pytest.mark.unit


def test_roles_to_clusters_maps_sap_role():
    assert roles_to_clusters(["SAP SD Consultant"]) == {"sap_erp"}


def test_roles_to_clusters_maps_role_aliases():
    assert roles_to_clusters(["QA Automation Engineer"]) == {"product_eng"}
    assert roles_to_clusters(["SDET"]) == {"product_eng"}


def test_roles_to_clusters_maps_innovation_roles():
    assert roles_to_clusters(["Innovation Engineer"]) == {"innovation"}
    assert roles_to_clusters(["Emerging Technologies Engineer"]) == {"innovation"}


def test_roles_to_clusters_maps_network_automation_roles():
    assert roles_to_clusters(["Network Automation Engineer"]) == {"network_auto"}
    assert roles_to_clusters(["Infrastructure Automation Engineer"]) == {"network_auto"}


def test_infer_clusters_from_job_text_detects_sap_jobs():
    clusters = infer_clusters_from_job_text(
        "Senior SAP SD Consultant",
        "Lead S/4HANA OTC implementation and SAP SD configuration for enterprise rollout.",
    )
    assert "sap_erp" in clusters
    assert "ai_ml" not in clusters


def test_infer_clusters_from_job_text_does_not_treat_sap_company_branding_as_erp():
    clusters = infer_clusters_from_job_text(
        "Senior Product Security Engineer",
        "At SAP, we help the world run better. Lead product security reviews and threat modeling.",
    )
    assert "sap_erp" not in clusters


def test_infer_clusters_from_job_text_detects_qa_jobs():
    clusters = infer_clusters_from_job_text(
        "QA Automation Engineer",
        "Build Selenium and Playwright automation suites and quality assurance pipelines.",
    )
    assert "product_eng" in clusters
    assert "ai_ml" not in clusters


def test_infer_clusters_from_job_text_detects_innovation_jobs():
    clusters = infer_clusters_from_job_text(
        "Innovation Engineer",
        "Drive rapid POCs, prototype development, IoT experiments, and emerging technology validation.",
    )
    assert "innovation" in clusters
    assert "product_eng" not in clusters


def test_infer_clusters_from_job_text_detects_network_automation_jobs():
    clusters = infer_clusters_from_job_text(
        "Network Automation Engineer",
        "Build Python-based firewall automation, routing workflows, cloud network reliability, and switching automation.",
    )
    assert "network_auto" in clusters
    assert "product_eng" not in clusters


def test_infer_clusters_from_job_text_avoids_short_token_false_positive():
    clusters = infer_clusters_from_job_text(
        "Software Development Engineer II, DSP Performance Tech",
        "We are looking for top notch SDEs to build scalable logistics software.",
    )
    assert "sap_erp" not in clusters
