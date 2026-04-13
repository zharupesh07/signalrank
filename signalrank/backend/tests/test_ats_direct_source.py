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


def test_ats_direct_active_registry_skips_disabled_boards():
    active = {
        (entry["company"], entry["site"], entry["slug"])
        for entry in ats_direct.active_companies()
    }

    assert ("Ada", "greenhouse", "ada") not in active
    assert ("Deepgram", "ashby", "deepgram") in active


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
