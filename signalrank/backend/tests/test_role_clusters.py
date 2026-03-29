from domain.role_clusters import infer_clusters_from_job_text, roles_to_clusters


def test_roles_to_clusters_maps_sap_role():
    assert roles_to_clusters(["SAP SD Consultant"]) == {"sap_erp"}


def test_roles_to_clusters_maps_role_aliases():
    assert roles_to_clusters(["QA Automation Engineer"]) == {"product_eng"}
    assert roles_to_clusters(["SDET"]) == {"product_eng"}


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


def test_infer_clusters_from_job_text_avoids_short_token_false_positive():
    clusters = infer_clusters_from_job_text(
        "Software Development Engineer II, DSP Performance Tech",
        "We are looking for top notch SDEs to build scalable logistics software.",
    )
    assert "sap_erp" not in clusters
