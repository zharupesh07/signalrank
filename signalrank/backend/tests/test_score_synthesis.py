import pytest

from domain.score_synthesis import synthesize_match_score


pytestmark = pytest.mark.unit


def test_synthesize_match_score_uses_verdict_and_verifier_adjustment():
    result = synthesize_match_score(
        deterministic_score=80.0,
        match_report={
            "verdict": "strong_fit",
            "confidence": 0.82,
            "target_lane_fit": "direct",
            "why_rank_up": ["shares skills: python"],
            "why_rank_down": ["missing core skills: aws"],
        },
        verification_report={
            "final_confidence_adjustment": -0.1,
            "unsupported_claims": ["judge overstated skill coverage"],
        },
    )

    assert result["fit_band"] == "strong_fit"
    assert result["confidence_band"] == "medium"
    assert result["final_score"] == pytest.approx(78.4)
    assert "Strong fit" in result["explanation_summary"]
    assert "Verifier:" in result["explanation_summary"]
