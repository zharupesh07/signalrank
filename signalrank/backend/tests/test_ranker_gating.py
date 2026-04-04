import pandas as pd

from batch.ranker import _select_verifier_indices


def test_select_verifier_indices_prefers_uncertain_reports():
    df = pd.DataFrame({"final_score": [98, 92, 90, 87]})
    selected = [0, 1, 2, 3]
    match_reports = [
        {"verdict": "strong_fit", "confidence": 0.95},
        {"verdict": "adjacent_fit", "confidence": 0.79},
        {"verdict": "weak_fit", "confidence": 0.73},
        {"verdict": "misleading_fit", "confidence": 0.61},
    ]

    verifier_indices = _select_verifier_indices(
        df,
        selected,
        match_reports,
        {"ranking": {"agentic_matching": {"verifier_top_n": 2, "verifier_min_confidence": 0.8}}},
    )

    assert verifier_indices == [3, 2]


def test_select_verifier_indices_skips_high_confidence_strong_fits():
    df = pd.DataFrame({"final_score": [98, 92]})
    selected = [0, 1]
    match_reports = [
        {"verdict": "strong_fit", "confidence": 0.95},
        {"verdict": "adjacent_fit", "confidence": 0.93},
    ]

    verifier_indices = _select_verifier_indices(
        df,
        selected,
        match_reports,
        {"ranking": {"agentic_matching": {"verifier_top_n": 2, "verifier_min_confidence": 0.8}}},
    )

    assert verifier_indices == []
