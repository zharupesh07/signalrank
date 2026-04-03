"""Tests for domain/scoring.py — seniority, role/skill, location, recency, YOE extraction."""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

from domain.scoring import (
    calculate_role_and_skill_match_score,
    calculate_seniority_score,
    extract_required_yoe,
    location_tier,
    location_weight,
    recency_weight,
)


# ---------------------------------------------------------------------------
# recency_weight
# ---------------------------------------------------------------------------

def _recency_cfg(enabled=True, half_life=21):
    return {"ranking": {"enable_recency_decay": enabled, "recency_half_life_days": half_life}}


def test_recency_weight_disabled():
    assert recency_weight({"ranking": {}}, "2026-01-01") == 1.0


def test_recency_weight_no_date():
    assert recency_weight(_recency_cfg(), None) == 1.0


def test_recency_weight_recent_date():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    w = recency_weight(_recency_cfg(), yesterday)
    assert 0.9 < w <= 1.0


def test_recency_weight_old_date():
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    w = recency_weight(_recency_cfg(), old)
    assert 0.0 < w < 0.2


def test_recency_weight_invalid_date():
    assert recency_weight(_recency_cfg(), "not-a-date") == 1.0


def test_recency_weight_z_suffix():
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    w = recency_weight(_recency_cfg(), recent)
    assert 0.8 < w <= 1.0


# ---------------------------------------------------------------------------
# calculate_seniority_score
# ---------------------------------------------------------------------------

_SENIORITY_CFG = {
    "ranking": {
        "seniority_penalty": {
            "junior_multiplier": 0.4,
            "low_yoe_multiplier": 0.5,
            "over_senior_multiplier": 0.7,
            "title_keywords": {
                "junior": ["junior", "intern", "trainee"],
                "over_senior": ["vp", "director", "cto"],
            },
        },
        "seniority_boosting_keywords": ["senior", "lead", "staff", "principal"],
    }
}


def test_seniority_junior_penalty():
    assert calculate_seniority_score(_SENIORITY_CFG, title="Junior Developer", description="") == 0.4


def test_seniority_intern_penalty():
    assert calculate_seniority_score(_SENIORITY_CFG, title="ML Intern", description="") == 0.4


def test_seniority_low_yoe_description():
    assert calculate_seniority_score(_SENIORITY_CFG, title="Engineer", description="Requires 0-2 years experience") == 0.5


def test_seniority_over_senior():
    assert calculate_seniority_score(_SENIORITY_CFG, title="VP Engineering", description="") == 0.7


def test_seniority_senior_boost():
    score = calculate_seniority_score(_SENIORITY_CFG, title="Senior Engineer", description="")
    assert score == pytest.approx(1.08)


def test_seniority_neutral():
    score = calculate_seniority_score(_SENIORITY_CFG, title="Software Engineer", description="5+ years")
    assert score == 1.0


def test_seniority_yoe_alignment_close():
    score = calculate_seniority_score(
        _SENIORITY_CFG, title="Senior Engineer", description="requires 5 years experience", user_yoe=5
    )
    assert score == pytest.approx(min(1.08 * 1.05, 1.15))


def test_seniority_yoe_alignment_far():
    score = calculate_seniority_score(
        _SENIORITY_CFG, title="Engineer", description="requires 10 years experience", user_yoe=2
    )
    assert score == pytest.approx(0.9)


def test_seniority_capped_at_115():
    score = calculate_seniority_score(
        _SENIORITY_CFG, title="Senior Staff Principal Lead", description="requires 5 years", user_yoe=5
    )
    assert score <= 1.15


# ---------------------------------------------------------------------------
# calculate_role_and_skill_match_score
# ---------------------------------------------------------------------------

def _role_cfg(positives=None, negatives=None):
    return {
        "ranking": {
            "positive_skill_keywords": positives or {},
            "negative_role_keywords": negatives or {},
        }
    }


def test_role_skill_neutral():
    assert calculate_role_and_skill_match_score(_role_cfg(), title="Engineer", description="") == 1.0


def test_role_skill_positive_boost():
    cfg = _role_cfg(positives={"machine learning": 1.15})
    score = calculate_role_and_skill_match_score(cfg, title="ML Engineer", description="machine learning")
    assert score > 1.0


def test_role_skill_negative_penalty():
    cfg = _role_cfg(negatives={"receptionist": 0.7})
    score = calculate_role_and_skill_match_score(cfg, title="Receptionist", description="")
    assert score < 1.0


def test_role_skill_clamped_low():
    cfg = _role_cfg(negatives={"a": 0.5, "b": 0.5, "c": 0.5})
    score = calculate_role_and_skill_match_score(cfg, title="a b c", description="")
    assert score == 0.6


def test_role_skill_clamped_high():
    cfg = _role_cfg(positives={"a": 1.5, "b": 1.5})
    score = calculate_role_and_skill_match_score(cfg, title="a b", description="")
    assert score == 1.4


# ---------------------------------------------------------------------------
# location_weight
# ---------------------------------------------------------------------------


def test_location_weight_no_prefs():
    assert location_weight("Bangalore", {"location_scoring": {}}) == 1.0


def test_location_weight_match():
    cfg = {"location_scoring": {"preferred_locations": ["Bangalore", "Remote"], "preferred_weight": 1.3}}
    assert location_weight("Bangalore, India", cfg) == 1.3


def test_location_weight_no_match():
    cfg = {"location_scoring": {"preferred_locations": ["Bangalore"], "preferred_weight": 1.3}}
    assert location_weight("New York, USA", cfg) == 1.0


def test_location_weight_empty_location():
    cfg = {"location_scoring": {"preferred_locations": ["Bangalore"], "preferred_weight": 1.3}}
    assert location_weight("", cfg) == 1.0


def test_location_weight_case_insensitive():
    cfg = {"location_scoring": {"preferred_locations": ["REMOTE"], "preferred_weight": 1.2}}
    assert location_weight("Remote - India", cfg) == 1.2


def test_location_tier_remote_preference():
    cfg = {"location_scoring": {"preferred_locations": ["Remote"], "want_remote": True}}
    assert location_tier("Remote - India", "Fully remote role", cfg) == 100


def test_location_tier_india_fallback():
    cfg = {"location_scoring": {"preferred_locations": ["Bangalore"]}}
    assert location_tier("KA, IN", "Onsite role", cfg) == 50


# ---------------------------------------------------------------------------
# extract_required_yoe
# ---------------------------------------------------------------------------


def test_yoe_simple():
    assert extract_required_yoe("5 years of experience") == 5


def test_yoe_range():
    assert extract_required_yoe("3-5 years of experience") == 5


def test_yoe_plus():
    assert extract_required_yoe("5+ years required") == 5


def test_yoe_minimum():
    assert extract_required_yoe("minimum 3 years") == 3


def test_yoe_at_least():
    assert extract_required_yoe("at least 7 years") == 7


def test_yoe_multiple_mentions():
    assert extract_required_yoe("3 years Python, 5-8 years ML") == 8


def test_yoe_none():
    assert extract_required_yoe("No experience required") is None


def test_yoe_non_string():
    assert extract_required_yoe(123) is None
