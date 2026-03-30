import pytest
from unittest.mock import MagicMock

from batch.query_builder import build_queries

pytestmark = pytest.mark.unit


def _mock_profile(**kwargs):
    p = MagicMock()
    p.target_roles = kwargs.get("target_roles")
    p.preferred_locations = kwargs.get("preferred_locations")
    p.custom_search_queries = kwargs.get("custom_search_queries")
    p.config_overrides = kwargs.get("config_overrides")
    return p


def test_basic_queries():
    p = _mock_profile(target_roles=["ML Engineer"], preferred_locations=["Bangalore"])
    queries = build_queries(p)
    assert len(queries) == 1
    assert queries[0].term == "ML Engineer"
    assert queries[0].location == "Bangalore"


def test_custom_queries_added():
    p = _mock_profile(
        target_roles=["ML Engineer"],
        preferred_locations=["Pune"],
        custom_search_queries=["LLM Infra"],
    )
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "ML Engineer" in terms
    assert "LLM Infra" in terms


def test_dedup_case_insensitive():
    p = _mock_profile(
        target_roles=["ML Engineer"],
        custom_search_queries=["ml engineer"],
        preferred_locations=["Remote"],
    )
    queries = build_queries(p)
    assert len(queries) == 1


def test_fallback_to_config_overrides():
    p = _mock_profile(
        target_roles=None,
        preferred_locations=None,
        custom_search_queries=None,
        config_overrides={
            "profile_intent": {"roles": ["Data Scientist"]},
            "scraping": {"locations": ["Mumbai"]},
        },
    )
    queries = build_queries(p)
    assert len(queries) == 1
    assert queries[0].term == "Data Scientist"
    assert queries[0].location == "Mumbai"


def test_cap_at_50():
    p = _mock_profile(
        target_roles=[f"Role {i}" for i in range(20)],
        preferred_locations=[f"City {j}" for j in range(10)],
    )
    queries = build_queries(p, max_terms=20)
    assert len(queries) <= 50


def test_default_country_when_no_locations():
    p = _mock_profile(target_roles=["Engineer"], preferred_locations=None)
    queries = build_queries(p)
    assert len(queries) == 1
    # "India" is country-like, normalized to city="" for country-wide jobspy search
    assert queries[0].location == ""
    assert queries[0].country == "India"


def test_role_alias_expands_to_relevant_query_terms():
    p = _mock_profile(target_roles=["QA Automation Engineer"], preferred_locations=["Pune"])
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "QA Automation Engineer" in terms
    assert "SDET" in terms
    assert "Test Engineer" in terms


def test_sap_queries_stay_narrow_to_erp_roles():
    p = _mock_profile(target_roles=["SAP SD Consultant"], preferred_locations=["Bangalore"])
    queries = build_queries(p, max_terms=10)
    terms = {q.term for q in queries}
    assert "SAP SD Consultant" in terms
    assert "SAP OTC Consultant" in terms
    assert "SAP S/4HANA SD Consultant" in terms
    assert "SAP Consultant" not in terms
