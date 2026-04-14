from unittest.mock import AsyncMock

import pytest

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig
from batch.sources import company_portals


def _job(url: str, title: str, location: str, description: str) -> RawJob:
    return RawJob(
        job_url=url,
        title=title,
        company="Optum",
        description=description,
        location=location,
        site="company_portal",
        date_posted=None,
    )


def test_company_portals_active_companies_respects_allowlist():
    names = {item["company"] for item in company_portals.active_companies(["Optum", "SAP"])}
    assert names == {"Optum", "SAP"}


@pytest.mark.asyncio
async def test_company_portals_search_fetches_and_filters(monkeypatch):
    monkeypatch.setattr(
        company_portals,
        "active_companies",
        lambda allowlist=None: [{"company": "Optum", "slug": "optum", "kind": "optum"}],
    )
    monkeypatch.setattr(company_portals, "load_cached_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr(company_portals, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(
        company_portals,
        "_fetch_company_jobs",
        AsyncMock(
            return_value=[
                _job(
                    "https://example.com/1",
                    "Senior AI Engineer",
                    "Bangalore, India",
                    "Agentic AI platform with 6-8 years experience",
                ),
                _job(
                    "https://example.com/2",
                    "Sales Consultant",
                    "Bangalore, India",
                    "Consulting role with SAP and ERP",
                ),
            ]
        ),
    )

    results = await company_portals.search(
        [SearchQuery(term="Agentic AI Engineer", location="Bangalore", country="India")],
        ScraperConfig(company_allowlist=["Optum"]),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/1"]


@pytest.mark.asyncio
async def test_company_portals_search_uses_cache_without_fetch(monkeypatch):
    cached_jobs = [
        _job(
            "https://example.com/cached",
            "Senior AI Engineer",
            "Bangalore, India",
            "Agentic AI platform with 6-8 years experience",
        )
    ]
    monkeypatch.setattr(
        company_portals,
        "active_companies",
        lambda allowlist=None: [{"company": "Optum", "slug": "optum", "kind": "optum"}],
    )
    monkeypatch.setattr(company_portals, "load_cached_jobs", AsyncMock(return_value=cached_jobs))
    monkeypatch.setattr(
        company_portals,
        "_fetch_company_jobs",
        AsyncMock(side_effect=AssertionError("cache miss")),
    )

    results = await company_portals.search(
        [SearchQuery(term="Agentic AI Engineer", location="Bangalore", country="India")],
        ScraperConfig(company_allowlist=["Optum"]),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/cached"]
