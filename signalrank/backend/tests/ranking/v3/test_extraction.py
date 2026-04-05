from ranking.v3.extraction import (
    parse_role_dates,
    compute_skill_recency_weights,
    extract_profile_v3,
)
from ranking.v3.profile import ProfileV3


def test_parse_role_dates_recent():
    text = """
    Network Engineer, Cisco  Jan 2024 – Present
    Skills: BGP, OSPF, firewall, Juniper
    """
    roles = parse_role_dates(text)
    assert len(roles) >= 1
    latest = max(roles, key=lambda r: r["end_year"])
    assert latest["end_year"] >= 2024


def test_parse_role_dates_old_role():
    text = """
    Software Engineer, Infosys  2015 – 2018
    Skills: Java, Spring Boot
    """
    roles = parse_role_dates(text)
    assert len(roles) >= 1
    assert roles[0]["end_year"] <= 2018


def test_compute_skill_recency_weights_recent_skill_is_high(monkeypatch):
    import ranking.v3.extraction as ext
    monkeypatch.setattr(ext, "_current_year", lambda: 2026)
    roles = [{"skills": ["pytorch", "transformers"], "end_year": 2025}]
    weights = compute_skill_recency_weights(roles)
    assert weights["pytorch"] >= 0.9
    assert weights["transformers"] >= 0.9


def test_compute_skill_recency_weights_old_skill_is_low(monkeypatch):
    import ranking.v3.extraction as ext
    monkeypatch.setattr(ext, "_current_year", lambda: 2026)
    roles = [{"skills": ["cobol", "fortran"], "end_year": 2015}]
    weights = compute_skill_recency_weights(roles)
    assert weights["cobol"] <= 0.4


def test_current_focus_boosts_skill_weight(monkeypatch):
    import ranking.v3.extraction as ext
    monkeypatch.setattr(ext, "_current_year", lambda: 2026)
    roles = [{"skills": ["firewall", "java"], "end_year": 2018}]
    weights = compute_skill_recency_weights(roles, current_focus="network firewall")
    assert weights["firewall"] == 1.0
    assert weights["java"] <= 0.4


def test_extract_profile_v3_returns_profile_v3():
    resume_text = """
    Aditya Kumar
    Network Engineer, Cisco  Jan 2023 – Present
    Skills: Cisco, BGP, firewall, Juniper, OSPF
    Python Developer, Infosys  2015 – 2020
    Skills: Python, Java, Spring Boot
    """
    profile = extract_profile_v3(resume_text, candidate_name="aditya")
    assert isinstance(profile, ProfileV3)
    assert "network" in profile.active_lanes
    assert any(ws.name in ("cisco", "bgp", "firewall", "juniper", "ospf") for ws in profile.weighted_skills)
