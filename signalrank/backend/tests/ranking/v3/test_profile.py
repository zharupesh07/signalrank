from ranking.v3.profile import ProfileV3, WeightedSkill


def test_weighted_skill_clamps_weight():
    s = WeightedSkill(name="python", weight=1.5)
    assert s.weight == 1.0


def test_weighted_skill_min_weight():
    s = WeightedSkill(name="cobol", weight=-0.1)
    assert s.weight == 0.0


def test_profile_v3_active_lanes_default_empty():
    p = ProfileV3(
        candidate_name="test",
        target_roles=["ML Engineer"],
        weighted_skills=[WeightedSkill(name="python", weight=1.0)],
        domains=["AI / ML"],
        industries=["Tech"],
        seniority_band="senior",
        preferred_locations=["Remote"],
        must_have_terms=["pytorch"],
        avoid_terms=["QA"],
        current_focus=None,
        active_lanes=[],
    )
    assert p.active_lanes == []


def test_profile_v3_with_current_focus():
    p = ProfileV3(
        candidate_name="aditya",
        target_roles=["Network Engineer"],
        weighted_skills=[WeightedSkill(name="firewall", weight=1.0)],
        domains=["Network / Infrastructure Automation"],
        industries=["Tech"],
        seniority_band="senior",
        preferred_locations=["Bangalore"],
        must_have_terms=["cisco"],
        avoid_terms=["junior"],
        current_focus="network automation",
        active_lanes=["network"],
    )
    assert p.current_focus == "network automation"
    assert "network" in p.active_lanes
