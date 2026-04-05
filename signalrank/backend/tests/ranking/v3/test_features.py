import pytest
from ranking.v3.profile import ProfileV3, WeightedSkill
from ranking.v3.features import (
    title_similarity,
    skill_overlap,
    role_family_match,
    description_role_family_terms,
    must_have_hits,
    negative_hits,
    seniority_match,
    domain_match,
    location_match,
    recency_bonus,
    compute_features,
)


def _make_profile(**kwargs) -> ProfileV3:
    defaults = dict(
        candidate_name="test",
        target_roles=["ML Engineer"],
        weighted_skills=[WeightedSkill("pytorch", 1.0), WeightedSkill("python", 0.8)],
        domains=["AI / ML"],
        industries=["Tech"],
        seniority_band="senior",
        preferred_locations=["Remote"],
        must_have_terms=["pytorch", "python"],
        avoid_terms=["qa", "support"],
        current_focus=None,
        active_lanes=[],
    )
    defaults.update(kwargs)
    return ProfileV3(**defaults)


def _make_job(**kwargs) -> dict:
    defaults = dict(
        title="Machine Learning Engineer",
        description="We need a senior ML engineer with pytorch and python skills.",
        location="Remote",
        seniority_band="senior",
        domain="AI / ML",
        date_posted="2026-03-01",
    )
    defaults.update(kwargs)
    return defaults


def test_title_similarity_exact_match():
    profile = _make_profile(target_roles=["ML Engineer"])
    job = _make_job(title="ML Engineer")
    assert title_similarity(job, profile) >= 0.9


def test_title_similarity_no_match():
    profile = _make_profile(target_roles=["ML Engineer"])
    job = _make_job(title="QA Automation Tester")
    assert title_similarity(job, profile) < 0.4


def test_title_similarity_caps_weak_ai_overlap():
    profile = _make_profile(target_roles=["Conversational AI Engineer"])
    job = _make_job(title="Software Engineer (AI Developer)")
    assert title_similarity(job, profile) <= 0.45


def test_skill_overlap_high():
    profile = _make_profile(
        weighted_skills=[WeightedSkill("pytorch", 1.0), WeightedSkill("python", 0.9)]
    )
    job = _make_job(description="Senior role requiring pytorch, python, transformers.")
    assert skill_overlap(job, profile) >= 0.5


def test_skill_overlap_zero():
    profile = _make_profile(
        weighted_skills=[WeightedSkill("cobol", 0.2)]
    )
    job = _make_job(description="React and TypeScript frontend role.")
    assert skill_overlap(job, profile) == 0.0


def test_role_family_match_hit():
    profile = _make_profile(active_lanes=["innovation"])
    job = _make_job(description="Lead innovation and prototyping R&D projects in our labs.")
    assert role_family_match(job, profile) == 1.0


def test_role_family_match_miss():
    profile = _make_profile(active_lanes=["innovation"])
    job = _make_job(description="QA engineer for regression testing.")
    assert role_family_match(job, profile) == 0.0


def test_role_family_match_no_active_lanes_returns_zero():
    profile = _make_profile(active_lanes=[])
    job = _make_job(description="Any job description.")
    assert role_family_match(job, profile) == 0.0


def test_role_family_match_single_term_is_soft_for_multi_lane_profiles():
    profile = _make_profile(active_lanes=["innovation", "iot"])
    job = _make_job(description="Build embedded monitoring workflows.")
    assert role_family_match(job, profile) == 0.35


def test_description_role_family_terms_normalized():
    profile = _make_profile(active_lanes=["network"])
    job = _make_job(description="Cisco firewall routing BGP OSPF network automation engineer.")
    score = description_role_family_terms(job, profile)
    assert 0.0 < score <= 1.0


def test_must_have_hits_full():
    profile = _make_profile(must_have_terms=["pytorch", "python"])
    job = _make_job(description="Requires pytorch and python experience.")
    assert must_have_hits(job, profile) == 1.0


def test_must_have_hits_none():
    profile = _make_profile(must_have_terms=["pytorch"])
    job = _make_job(description="Java Spring Boot backend role.")
    assert must_have_hits(job, profile) == 0.0


def test_negative_hits_present():
    profile = _make_profile(avoid_terms=["qa", "support"])
    job = _make_job(title="QA Engineer", description="Support testing workflows.")
    assert negative_hits(job, profile) > 0.0


def test_negative_hits_absent():
    profile = _make_profile(avoid_terms=["qa", "support"])
    job = _make_job(title="ML Engineer", description="Build ML pipelines.")
    assert negative_hits(job, profile) == 0.0


def test_seniority_match_exact():
    profile = _make_profile(seniority_band="senior")
    job = _make_job(seniority_band="senior")
    assert seniority_match(job, profile) == 1.0


def test_seniority_match_mismatch():
    profile = _make_profile(seniority_band="senior")
    job = _make_job(seniority_band="junior")
    assert seniority_match(job, profile) == -1.0


def test_seniority_match_unknown():
    profile = _make_profile(seniority_band="senior")
    job = _make_job(seniority_band="unknown")
    assert seniority_match(job, profile) == 0.0


def test_domain_match_hit():
    profile = _make_profile(domains=["AI / ML"])
    job = _make_job(domain="AI / ML")
    assert domain_match(job, profile) == 1.0


def test_domain_match_miss():
    profile = _make_profile(domains=["AI / ML"])
    job = _make_job(domain="SAP / ERP")
    assert domain_match(job, profile) == 0.0


def test_location_match_exact():
    profile = _make_profile(preferred_locations=["Remote"])
    job = _make_job(location="Remote")
    assert location_match(job, profile) == 1.0


def test_location_match_remote_ok():
    profile = _make_profile(preferred_locations=["Bangalore"])
    job = _make_job(location="Remote")
    assert location_match(job, profile) == 0.5


def test_location_match_no_match():
    profile = _make_profile(preferred_locations=["Bangalore"])
    job = _make_job(location="London")
    assert location_match(job, profile) == 0.0


def test_recency_bonus_recent_skill_match():
    profile = _make_profile(
        weighted_skills=[WeightedSkill("pytorch", 1.0), WeightedSkill("python", 0.9)]
    )
    job = _make_job(description="pytorch python transformers")
    assert recency_bonus(job, profile) >= 0.8


def test_recency_bonus_old_skill_match():
    profile = _make_profile(
        weighted_skills=[WeightedSkill("cobol", 0.2)]
    )
    job = _make_job(description="cobol fortran legacy systems")
    assert recency_bonus(job, profile) <= 0.3


def test_compute_features_returns_all_10():
    profile = _make_profile()
    job = _make_job()
    feats = compute_features(job, profile)
    assert len(feats) == 10
    expected_keys = {
        "title_similarity", "skill_overlap", "role_family_match",
        "description_role_family_terms", "must_have_hits", "negative_hits",
        "seniority_match", "domain_match", "location_match", "recency_bonus",
    }
    assert set(feats.keys()) == expected_keys
