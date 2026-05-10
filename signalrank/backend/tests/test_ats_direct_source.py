from unittest.mock import AsyncMock

import pytest

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig
from batch.sources import ats_direct


def test_ats_direct_company_registry_contains_expected_direct_boards():
    companies = {
        (entry["company"], entry["site"], entry["slug"])
        for entry in ats_direct._ATS_COMPANIES
    }

    assert ("Mistral AI", "lever", "mistral") in companies
    assert ("Clay Labs", "ashby", "claylabs") in companies
    assert ("Databricks", "greenhouse", "databricks") in companies
    assert ("Snowflake", "ashby", "snowflake") in companies
    assert ("Netskope", "greenhouse", "netskope") in companies
    assert ("Rubrik", "greenhouse", "rubrik") in companies
    assert ("Okta", "greenhouse", "okta") in companies
    assert ("Coinbase", "greenhouse", "coinbase") in companies
    assert ("Cloudflare", "greenhouse", "cloudflare") in companies
    assert ("Twilio", "greenhouse", "twilio") in companies
    assert ("Agoda", "greenhouse", "agoda") in companies
    assert ("Uber Freight", "greenhouse", "uberfreight") in companies
    assert ("PhonePe", "greenhouse", "phonepe") in companies
    assert ("Razorpay", "greenhouse", "razorpaysoftwareprivatelimited") in companies
    assert ("Groww", "greenhouse", "groww") in companies
    assert ("Postman", "greenhouse", "postman") in companies
    assert ("CRED", "lever", "cred") in companies
    assert ("Dream Sports", "lever", "dreamsports") in companies
    assert ("Meesho", "lever", "meesho") in companies
    assert ("Zeta", "lever", "zeta") in companies
    assert ("Atlassian", "lever", "atlassian") in companies
    assert ("Airbnb", "greenhouse", "airbnb") in companies
    assert ("Stripe", "greenhouse", "stripe") in companies
    assert ("Freshworks", "smartrecruiters", "Freshworks") in companies
    assert ("GitLab", "greenhouse", "gitlab") in companies
    assert ("OpenAI", "ashby", "openai") not in companies
    assert ("Anthropic", "greenhouse", "anthropic") not in companies
    assert ("ServiceNow", "workday", "servicenow") not in companies
    assert ("Uber", "greenhouse", "uber") not in companies
    assert ("Microsoft", "greenhouse", "microsoft") not in companies
    assert ("Google", "greenhouse", "google") not in companies
    assert ("Confluent", "ashby", "confluent") not in companies
    assert ("Elastic", "greenhouse", "elastic") not in companies
    assert ("Harness", "greenhouse", "harnessinc") not in companies
    assert ("Together AI", "greenhouse", "togetherai") not in companies
    assert ("Modal", "ashby", "modal") not in companies


def test_ats_direct_active_registry_skips_disabled_boards():
    active = {
        (entry["company"], entry["site"], entry["slug"])
        for entry in ats_direct.active_companies()
    }

    assert ("Ada", "greenhouse", "ada") not in active
    assert ("Deepgram", "ashby", "deepgram") in active
    assert ("OpenAI", "ashby", "openai") not in active
    assert ("Databricks", "greenhouse", "databricks") in active
    assert ("Snowflake", "ashby", "snowflake") in active
    assert ("Netskope", "greenhouse", "netskope") in active
    assert ("Rubrik", "greenhouse", "rubrik") in active
    assert ("Okta", "greenhouse", "okta") in active
    assert ("Coinbase", "greenhouse", "coinbase") in active
    assert ("Cloudflare", "greenhouse", "cloudflare") in active
    assert ("Twilio", "greenhouse", "twilio") in active
    assert ("Agoda", "greenhouse", "agoda") in active
    assert ("Uber Freight", "greenhouse", "uberfreight") in active
    assert ("PhonePe", "greenhouse", "phonepe") in active
    assert ("Razorpay", "greenhouse", "razorpaysoftwareprivatelimited") in active
    assert ("Groww", "greenhouse", "groww") in active
    assert ("Postman", "greenhouse", "postman") in active
    assert ("CRED", "lever", "cred") in active
    assert ("Dream Sports", "lever", "dreamsports") in active
    assert ("Meesho", "lever", "meesho") in active
    assert ("Zeta", "lever", "zeta") in active
    assert ("Confluent", "ashby", "confluent") not in active
    assert ("Elastic", "greenhouse", "elastic") not in active
    assert ("Atlassian", "lever", "atlassian") in active
    assert ("Airbnb", "greenhouse", "airbnb") in active
    assert ("Stripe", "greenhouse", "stripe") in active
    assert ("Freshworks", "smartrecruiters", "Freshworks") in active
    assert ("GitLab", "greenhouse", "gitlab") in active
    assert ("Harness", "greenhouse", "harnessinc") not in active


def test_ats_direct_api_url_builder_supports_all_sites():
    assert ats_direct._api_url(
        {"company": "Ada", "site": "greenhouse", "slug": "ada"}
    ) == "https://boards-api.greenhouse.io/v1/boards/ada/jobs"
    assert ats_direct._api_url(
        {"company": "Clay Labs", "site": "ashby", "slug": "claylabs"}
    ) == "https://api.ashbyhq.com/posting-api/job-board/claylabs?includeCompensation=true"
    assert ats_direct._api_url(
        {"company": "Mistral AI", "site": "lever", "slug": "mistral"}
    ) == "https://api.lever.co/v0/postings/mistral"
    assert ats_direct._api_url(
        {"company": "Freshworks", "site": "smartrecruiters", "slug": "Freshworks"}
    ) == "https://careers.smartrecruiters.com/Freshworks"


def test_ats_direct_normalizes_greenhouse_ashby_and_lever_payloads():
    greenhouse_jobs = ats_direct._normalize_greenhouse(
        {"company": "Acme"},
        {
            "jobs": [
                {
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    "title": "Backend Engineer",
                    "content": "<p>Python APIs</p>",
                    "location": {"name": "Remote"},
                    "first_published": "2026-05-01T00:00:00Z",
                }
            ]
        },
    )
    ashby_jobs = ats_direct._normalize_ashby(
        {"company": "Acme"},
        {
            "jobs": [
                {
                    "jobUrl": "https://jobs.ashbyhq.com/acme/2",
                    "title": "Frontend Engineer",
                    "descriptionPlain": "React UI",
                    "location": "Pune",
                    "publishedDate": "2026-05-02T00:00:00Z",
                }
            ]
        },
    )
    lever_jobs = ats_direct._normalize_lever(
        {"company": "Acme"},
        [
            {
                "hostedUrl": "https://jobs.lever.co/acme/3",
                "text": "Data Engineer",
                "descriptionPlain": "Spark pipelines",
                "categories": {"location": "Bangalore"},
            }
        ],
    )

    assert greenhouse_jobs[0].site == "greenhouse"
    assert greenhouse_jobs[0].location == "Remote"
    assert ashby_jobs[0].site == "ashby"
    assert ashby_jobs[0].description == "React UI"
    assert lever_jobs[0].site == "lever"
    assert lever_jobs[0].title == "Data Engineer"


def test_ats_direct_matches_query_applies_title_and_location_filter():
    job = RawJob(
        job_url="https://example.com/frontend",
        title="Frontend Engineer",
        company="Acme",
        description="Build React and TypeScript interfaces",
        location="Pune, India",
        site="ashby",
        date_posted=None,
    )

    assert ats_direct._matches_query(
        job, SearchQuery(term="Frontend Engineer", location="Pune", country="India")
    )
    assert not ats_direct._matches_query(
        job, SearchQuery(term="Backend Engineer", location="Pune", country="India")
    )
    assert not ats_direct._matches_query(
        job, SearchQuery(term="Frontend Engineer", location="Bangalore", country="India")
    )


@pytest.mark.asyncio
async def test_probe_company_reports_status(monkeypatch):
    class _Response:
        status_code = 200
        url = "https://example.com"

    client = AsyncMock()
    client.get.return_value = _Response()

    result = await ats_direct.probe_company(
        client,
        {"company": "Deepgram", "site": "ashby", "slug": "deepgram"},
    )

    assert result["company"] == "Deepgram"
    assert result["status"] == 200


@pytest.mark.asyncio
async def test_ats_direct_search_filters_relevant_roles(monkeypatch):
    monkeypatch.setattr(
        ats_direct,
        "_ATS_COMPANIES",
        [{"company": "Anthropic", "site": "greenhouse", "slug": "anthropic"}],
    )
    monkeypatch.setattr(ats_direct, "load_cached_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr(ats_direct, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(
        ats_direct,
        "_fetch_board",
        AsyncMock(
            return_value=[
                RawJob(
                    job_url="https://example.com/ml-platform",
                    title="AI Platform Engineer",
                    company="Anthropic",
                    description="Build platform, inference, kubernetes, python systems",
                    location="Remote",
                    site="greenhouse",
                    date_posted=None,
                ),
                RawJob(
                    job_url="https://example.com/finance",
                    title="Finance Manager",
                    company="Anthropic",
                    description="Own finance planning and reporting",
                    location="Remote",
                    site="greenhouse",
                    date_posted=None,
                ),
            ]
        ),
    )

    results = await ats_direct.search(
        [SearchQuery(term="AI Platform Engineer", location="Remote", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/ml-platform"]


@pytest.mark.asyncio
async def test_ats_direct_search_uses_cache_without_fetch(monkeypatch):
    cached_jobs = [
        RawJob(
            job_url="https://example.com/cached",
            title="MLOps Engineer",
            company="Anthropic",
            description="MLOps and platform systems",
            location="Remote",
            site="greenhouse",
            date_posted=None,
        )
    ]
    monkeypatch.setattr(
        ats_direct,
        "_ATS_COMPANIES",
        [{"company": "Anthropic", "site": "greenhouse", "slug": "anthropic"}],
    )
    monkeypatch.setattr(ats_direct, "load_cached_jobs", AsyncMock(return_value=cached_jobs))
    monkeypatch.setattr(ats_direct, "_fetch_board", AsyncMock(side_effect=AssertionError("cache miss")))

    results = await ats_direct.search(
        [SearchQuery(term="MLOps Engineer", location="", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/cached"]
