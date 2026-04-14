from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from batch.context import load_base_config
from batch.scraper import ScraperConfig
from batch.sources import ats_direct, company_portals, workday
from domain.company import CompanyScorer
from ranking.profile_fresh_rank import rank_profile_fresh_jobs, select_top_companies


def _job(
    title: str,
    *,
    company: str = "Acme",
    location: str = "Bangalore, India",
    description: str = "",
    date_posted: datetime | None = None,
    site: str = "jobs.example.com",
    url: str = "https://example.com/job",
) -> dict:
    return {
        "job_url": url,
        "title": title,
        "company": company,
        "description": description,
        "location": location,
        "site": site,
        "date_posted": date_posted or datetime.now(timezone.utc) - timedelta(days=1),
    }


@pytest.fixture
def company_scorer() -> CompanyScorer:
    return CompanyScorer(load_base_config())


def test_rank_profile_fresh_jobs_rejects_geo_restricted_remote(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior GenAI Engineer",
            location="Remote - US",
            description="Remote USA generative AI role",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["geo_restricted_remote"] == 1


def test_rank_profile_fresh_jobs_rejects_remote_role_with_explicit_us_location(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Principal AI Engineer",
            location="US-NY-New York City-Remote",
            description="Build agent systems and AI platform tooling with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["geo_restricted_remote"] == 1


def test_rank_profile_fresh_jobs_rejects_non_india_location(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior MLOps Engineer",
            location="USA",
            description="MLOps and AI platform role with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["non_india_location"] == 1


def test_rank_profile_fresh_jobs_keeps_india_safe_remote(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior Agentic AI Engineer",
            company="Microsoft",
            location="Remote, India",
            description="Build agent platform and multi-agent orchestration systems with 6-8 years experience",
            url="https://example.com/india-remote",
        )
    ]

    ranked, _ = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert len(ranked) == 1
    assert ranked[0].location_bucket == "top"
    assert ranked[0].remote_policy_match == "india_safe"
    assert ranked[0].role_bucket == "agentic"


def test_rank_profile_fresh_jobs_rejects_non_target_adjacent_role(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior Backend Engineer",
            description="Build backend microservices on Google Cloud with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["role_mismatch"] == 1


def test_rank_profile_fresh_jobs_rejects_manager_titles(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Engineering Manager, AI Platform",
            description="Lead AI platform teams with 7-9 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["role_mismatch"] == 1


def test_rank_profile_fresh_jobs_rejects_sales_roles_with_ai_keywords(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Account Executive - Saudi",
            company="Snowflake",
            location="Saudi Arabia - Remote",
            description="Work with enterprise customers on AI agents and generative AI platform strategy with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["role_mismatch"] == 1


def test_rank_profile_fresh_jobs_rejects_solution_engineer_roles(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Principal AI/ML Solution Engineer",
            company="Snowflake",
            location="Remote, India",
            description="Help customers adopt agent systems with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["role_mismatch"] == 1


def test_rank_profile_fresh_jobs_rejects_product_engineer_roles(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Product Engineer - Auth",
            company="Supabase",
            location="Remote",
            description="Build generative AI auth flows and LLM integrations with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["role_mismatch"] == 1


def test_rank_profile_fresh_jobs_rejects_yoe_out_of_range(company_scorer: CompanyScorer):
    low = _job(
        "MLOps Engineer",
        description="Need 3 years experience with mlops and kubernetes",
        url="https://example.com/low",
    )
    high = _job(
        "Senior GenAI Engineer",
        description="Need 10+ years experience with llm systems",
        url="https://example.com/high",
    )

    ranked, rejections = rank_profile_fresh_jobs([low, high], company_scorer=company_scorer)

    assert ranked == []
    assert rejections["yoe_too_low"] == 1
    assert rejections["yoe_too_high"] == 1


def test_rank_profile_fresh_jobs_uses_location_field_over_description(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior GenAI Engineer",
            location="Noida, Uttar Pradesh, India",
            description="Remote collaboration with global teams on generative AI systems with 6-8 years experience",
            url="https://example.com/noida",
        )
    ]

    ranked, _ = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert len(ranked) == 1
    assert ranked[0].location_bucket == "acceptable"
    assert ranked[0].remote_policy_match == "city_match"


def test_rank_profile_fresh_jobs_rejects_remote_roles_with_explicit_us_cities(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Machine Learning Engineer, Stripe Assistant",
            company="Stripe",
            location="Seattle; San Francisco; New York City; Remote",
            description="Machine learning systems role with 6-8 years experience",
        )
    ]

    ranked, rejections = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)

    assert ranked == []
    assert rejections["geo_restricted_remote"] == 1


def test_location_priority_beats_acceptable_city_even_with_bump(company_scorer: CompanyScorer):
    remote = _job(
        "Senior GenAI Engineer",
        company="Microsoft",
        location="Remote, India",
        description="Generative AI systems and LLM services with 6-8 years experience",
        url="https://example.com/remote",
    )
    acceptable = _job(
        "Senior GenAI Engineer",
        company="Google",
        location="Hyderabad, India",
        description="Generative AI systems and LLM services with 6-8 years experience",
        url="https://example.com/acceptable",
    )

    ranked, _ = rank_profile_fresh_jobs([acceptable, remote], company_scorer=company_scorer)

    assert ranked[0].job_url == "https://example.com/remote"
    assert ranked[1].location_compensation == 5


def test_select_top_companies_uses_best_applyable_job(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior GenAI Engineer",
            company="Stripe",
            location="Bangalore, India",
            description="Generative AI services with 6-8 years experience",
            url="https://example.com/strong",
        ),
        _job(
            "Machine Learning Engineer",
            company="Stripe",
            location="Mumbai, India",
            description="Machine learning platform with 6-8 years experience",
            url="https://example.com/weaker",
        ),
    ]

    ranked, _ = rank_profile_fresh_jobs(jobs, company_scorer=company_scorer)
    rows = select_top_companies(ranked, limit=10)

    assert len(rows) == 1
    assert rows[0]["company"] == "Stripe"
    assert rows[0]["best_job_url"] == "https://example.com/strong"


def test_rank_profile_fresh_jobs_can_filter_to_allowed_companies(company_scorer: CompanyScorer):
    jobs = [
        _job(
            "Senior GenAI Engineer",
            company="Stripe",
            location="Bangalore, India",
            description="Generative AI services with 6-8 years experience",
            url="https://example.com/stripe",
        ),
        _job(
            "Senior GenAI Engineer",
            company="Databricks",
            location="Bangalore, India",
            description="Generative AI services with 6-8 years experience",
            url="https://example.com/databricks",
        ),
    ]

    ranked, rejections = rank_profile_fresh_jobs(
        jobs,
        company_scorer=company_scorer,
        allowed_companies=["Stripe"],
    )

    assert len(ranked) == 1
    assert ranked[0].company == "Stripe"
    assert rejections["company_filtered_out"] == 1


def test_active_companies_respects_allowlist():
    ats_names = {item["company"] for item in ats_direct.active_companies(["Snowflake", "Stripe"])}
    portal_names = {item["company"] for item in company_portals.active_companies(["Optum", "SAP"])}
    workday_names = {item["company"] for item in workday.active_companies(["Salesforce", "FIS"])}

    assert ats_names == {"Snowflake", "Stripe"}
    assert portal_names == {"Optum", "SAP"}
    assert workday_names == {"Salesforce", "FIS"}


def test_scraper_config_can_carry_company_allowlist():
    config = ScraperConfig(company_allowlist=["Salesforce", "Snowflake"])
    assert config.company_allowlist == ["Salesforce", "Snowflake"]
