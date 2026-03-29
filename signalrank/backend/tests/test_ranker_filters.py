from batch.ranker import matches_requested_clusters_for_row


def test_runtime_filter_ignores_polluted_stored_cluster_when_text_disagrees() -> None:
    assert not matches_requested_clusters_for_row(
        {"sap_erp"},
        ["sap_erp", "ai_ml"],
        "Lead Quantitative Analytics Specialist",
        "Build predictive AI solutions and hire top notch data science talent.",
    )


def test_runtime_filter_keeps_sparse_row_when_stored_cluster_matches() -> None:
    assert matches_requested_clusters_for_row(
        {"sap_erp"},
        ["sap_erp"],
        "ERP Specialist",
        "",
    )
