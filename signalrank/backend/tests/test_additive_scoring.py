"""Tests for domain/additive_scoring.py — all 5 scoring dimensions + weighted composite."""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

from domain.additive_scoring import (
    apply_company_semantic_floor,
    apply_hidden_gem_bonus,
    company_score_0_100,
    compute_weighted_score,
    detect_contract_type,
    detect_work_mode,
    location_score_0_100,
    recency_score_0_100,
    seniority_score_0_100,
    skills_score_0_100,
)


# ---------------------------------------------------------------------------
# skills_score_0_100
# ---------------------------------------------------------------------------


def test_skills_high_semantic():
    score = skills_score_0_100(0.90, skill_overlap=3, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    assert 90 <= score <= 100


def test_skills_low_semantic():
    score = skills_score_0_100(0.20, skill_overlap=0, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    assert 15 <= score <= 25


def test_skills_overlap_bonus():
    base = skills_score_0_100(0.50, skill_overlap=0, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    with_overlap = skills_score_0_100(0.50, skill_overlap=4, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    assert with_overlap == base + 8  # capped at 4*2=8


def test_skills_overlap_cap():
    s1 = skills_score_0_100(0.50, skill_overlap=4, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    s2 = skills_score_0_100(0.50, skill_overlap=10, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    assert s1 == s2  # both capped at +8


def test_skills_role_boost():
    base = skills_score_0_100(0.50, 0, role_skill_score=1.0, functional_role_penalty=1.0, consulting_damp=1.0)
    boosted = skills_score_0_100(0.50, 0, role_skill_score=1.2, functional_role_penalty=1.0, consulting_damp=1.0)
    assert boosted > base


def test_skills_consulting_penalty():
    base = skills_score_0_100(0.50, 0, 1.0, 1.0, consulting_damp=1.0)
    penalized = skills_score_0_100(0.50, 0, 1.0, 1.0, consulting_damp=0.8)
    assert penalized == base - 10


def test_skills_clamp_low():
    score = skills_score_0_100(0.0, 0, role_skill_score=0.5, functional_role_penalty=0.5, consulting_damp=0.5)
    assert score == 0.0


def test_skills_clamp_high():
    score = skills_score_0_100(1.0, 10, role_skill_score=1.5, functional_role_penalty=1.5, consulting_damp=1.0)
    assert score == 100.0


# ---------------------------------------------------------------------------
# company_score_0_100
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier,expected", [
    ("tier_ss", 100.0),
    ("tier_s", 95.0),
    ("tier_a", 85.0),
    ("tier_b", 65.0),
    ("tier_c", 45.0),
    ("tier_d", 15.0),
    ("preferred", 100.0),
    ("deprioritized", 15.0),
    ("unknown", 40.0),
    ("", 40.0),
])
def test_company_score_tiers(tier, expected):
    assert company_score_0_100(tier) == expected


# ---------------------------------------------------------------------------
# apply_company_semantic_floor
# ---------------------------------------------------------------------------


def test_semantic_floor_above():
    assert apply_company_semantic_floor(85.0, 0.80, 0.65) == 85.0


def test_semantic_floor_below():
    result = apply_company_semantic_floor(85.0, 0.50, 0.65)
    assert result == pytest.approx(85.0 * (0.50 / 0.65))


def test_semantic_floor_zero():
    assert apply_company_semantic_floor(85.0, 0.50, 0.0) == 85.0


# ---------------------------------------------------------------------------
# apply_hidden_gem_bonus
# ---------------------------------------------------------------------------


def test_hidden_gem_unknown_tier_high_semantic():
    assert apply_hidden_gem_bonus(40.0, "", 0.80) == 60.0


def test_hidden_gem_none_tier():
    assert apply_hidden_gem_bonus(40.0, None, 0.75) == 60.0


def test_hidden_gem_known_tier():
    assert apply_hidden_gem_bonus(40.0, "tier_a", 0.80) == 40.0


def test_hidden_gem_low_semantic():
    assert apply_hidden_gem_bonus(40.0, "", 0.50) == 40.0


# ---------------------------------------------------------------------------
# seniority_score_0_100
# ---------------------------------------------------------------------------


def test_seniority_min():
    assert seniority_score_0_100(0.4) == pytest.approx(10.0)


def test_seniority_max():
    assert seniority_score_0_100(1.15) == pytest.approx(100.0)


def test_seniority_mid():
    score = seniority_score_0_100(0.775)  # midpoint
    assert 50 <= score <= 60


def test_seniority_below_range():
    assert seniority_score_0_100(0.0) == 0.0


def test_seniority_above_range():
    assert seniority_score_0_100(2.0) == 100.0


# ---------------------------------------------------------------------------
# location_score_0_100
# ---------------------------------------------------------------------------


def test_location_preferred():
    assert location_score_0_100(1.3) == 100.0


def test_location_neutral():
    assert location_score_0_100(1.0) == 30.0


def test_location_below():
    assert location_score_0_100(0.5) == 30.0


# ---------------------------------------------------------------------------
# recency_score_0_100
# ---------------------------------------------------------------------------


def test_recency_none():
    assert recency_score_0_100(None) == 30.0


def test_recency_today():
    today = datetime.now(timezone.utc).isoformat()
    assert recency_score_0_100(today) == 100.0


def test_recency_7_days():
    d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    assert recency_score_0_100(d) == pytest.approx(80.0, abs=2)


def test_recency_14_days():
    d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    assert recency_score_0_100(d) == pytest.approx(60.0, abs=2)


def test_recency_30_days():
    d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert recency_score_0_100(d) == pytest.approx(30.0, abs=2)


def test_recency_old():
    d = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert recency_score_0_100(d) == 10.0


def test_recency_future():
    d = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert recency_score_0_100(d) == 100.0


def test_recency_invalid():
    assert recency_score_0_100("garbage") == 30.0


# ---------------------------------------------------------------------------
# detect_contract_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title,desc,expected", [
    ("Contract Developer", "", True),
    ("Part-Time Analyst", "", True),
    ("Software Engineer", "freelance position", True),
    ("Backend Dev", "8 hours per day mandatory", True),
    ("Senior SDE", "Full time permanent role at Google", False),
    ("Engineer", "", False),
])
def test_detect_contract(title, desc, expected):
    assert detect_contract_type(title, desc) is expected


# ---------------------------------------------------------------------------
# detect_work_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("location,title,description,expected", [
    # Remote signals in location
    ("Remote", "ML Engineer", "", "remote"),
    ("Work from Home", "Engineer", "", "remote"),
    ("remote - india", "Backend Dev", "", "remote"),
    # Remote signals in description
    ("KA, IN", "Engineer", "This is a fully remote position", "remote"),
    ("KA, IN", "Engineer", "work from home allowed", "remote"),
    ("KA, IN", "Engineer", "100% remote working", "remote"),
    # Hybrid signals
    ("Bangalore", "Engineer", "hybrid work model", "hybrid"),
    ("Bangalore", "Engineer", "2 days office per week", "hybrid"),
    ("Bangalore", "Engineer", "flexible work arrangement", "hybrid"),
    # Onsite (no signals)
    ("Bangalore", "Software Engineer", "Great company culture", "onsite"),
    ("MH, IN", "Data Engineer", "Join our team in Mumbai", "onsite"),
    # Unknown (empty)
    ("", "", "", "unknown"),
    (None, None, None, "unknown"),
])
def test_detect_work_mode(location, title, description, expected):
    assert detect_work_mode(location or "", title or "", description or "") == expected


# ---------------------------------------------------------------------------
# compute_weighted_score
# ---------------------------------------------------------------------------


def test_weighted_score_defaults():
    scores = {"skills_match": 80, "company_fit": 70, "seniority": 60, "location": 50, "recency": 40}
    result = compute_weighted_score(scores)
    expected = 80 * 0.40 + 70 * 0.20 + 60 * 0.15 + 50 * 0.15 + 40 * 0.10
    assert result == pytest.approx(expected)


def test_weighted_score_custom_weights():
    scores = {"skills_match": 100, "company_fit": 0, "seniority": 0, "location": 0, "recency": 0}
    result = compute_weighted_score(scores, {"skills_match": 1.0, "company_fit": 0, "seniority": 0, "location": 0, "recency": 0})
    assert result == pytest.approx(100.0)


def test_weighted_score_all_zeros():
    scores = {"skills_match": 0, "company_fit": 0, "seniority": 0, "location": 0, "recency": 0}
    assert compute_weighted_score(scores) == 0.0


def test_weighted_score_all_100():
    scores = {"skills_match": 100, "company_fit": 100, "seniority": 100, "location": 100, "recency": 100}
    assert compute_weighted_score(scores) == 100.0
