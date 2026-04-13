from unittest.mock import AsyncMock

import pytest

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig
from batch.sources import workday


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workday.asyncio, "sleep", _noop)


def test_workday_company_registry_contains_expected_boards():
    companies = {
        (entry["company"], entry["slug"], entry["tenant"], entry["site"])
        for entry in workday._WORKDAY_COMPANIES
    }

    assert ("Salesforce", "salesforce", "salesforce", "External_Career_Site") in companies
    assert ("Walmart", "walmart", "walmart", "WalmartExternal") in companies
    assert ("Adobe", "adobe", "adobe", "external_experienced") in companies
    assert ("BrowserStack", "browserstack", "browserstack", "External") in companies


def test_workday_url_builders_use_cxs_endpoints():
    company = {
        "company": "Autodesk",
        "slug": "autodesk",
        "host": "autodesk.wd1.myworkdayjobs.com",
        "tenant": "autodesk",
        "site": "Ext",
        "base_url": "https://autodesk.wd1.myworkdayjobs.com/Ext",
    }

    assert workday._list_url(company) == "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/jobs"
    assert workday._detail_url(company, "Software-Engineer_123") == "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/job/Software-Engineer_123"


def test_workday_matches_query_uses_tokens_and_location():
    summary = {
        "title": "Senior Software Engineer",
        "locationsText": "Bangalore, India",
    }
    detail = {
        "title": "Senior Software Engineer",
        "jobDescription": "Python platform and distributed systems role",
        "jobRequisitionLocation": {"descriptor": "Bangalore, India"},
        "remoteType": "Hybrid",
    }

    assert workday._matches_query(
        summary,
        detail,
        SearchQuery(term="Software Engineer", location="Bangalore", country="India"),
    )
    assert not workday._matches_query(
        summary,
        detail,
        SearchQuery(term="Finance Manager", location="Bangalore", country="India"),
    )
    assert not workday._matches_query(
        summary,
        detail,
        SearchQuery(term="Software Engineer", location="Pune", country="India"),
    )


@pytest.mark.asyncio
async def test_probe_company_reports_status(monkeypatch):
    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"total": 42}

    client = AsyncMock()
    client.post.return_value = _Response()

    result = await workday.probe_company(
        client,
        {
            "company": "Autodesk",
            "slug": "autodesk",
            "host": "autodesk.wd1.myworkdayjobs.com",
            "tenant": "autodesk",
            "site": "Ext",
            "base_url": "https://autodesk.wd1.myworkdayjobs.com/Ext",
        },
    )

    assert result["company"] == "Autodesk"
    assert result["status"] == 200
    assert result["total"] == 42


@pytest.mark.asyncio
async def test_workday_search_fetches_and_filters(monkeypatch):
    monkeypatch.setattr(
        workday,
        "_WORKDAY_COMPANIES",
        [
            {
                "company": "Autodesk",
                "slug": "autodesk",
                "host": "autodesk.wd1.myworkdayjobs.com",
                "tenant": "autodesk",
                "site": "Ext",
                "base_url": "https://autodesk.wd1.myworkdayjobs.com/Ext",
            }
        ],
    )
    monkeypatch.setattr(workday, "load_cached_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr(workday, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(
        workday,
        "_fetch_company_jobs",
        AsyncMock(
            return_value=[
                RawJob(
                    job_url="https://example.com/software-engineer",
                    title="Software Engineer",
                    company="Autodesk",
                    description="Python platform role",
                    location="Bangalore, India",
                    site="workday",
                    date_posted=None,
                )
            ]
        ),
    )

    results = await workday.search(
        [SearchQuery(term="Software Engineer", location="Bangalore", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/software-engineer"]


@pytest.mark.asyncio
async def test_workday_search_uses_cache_without_fetch(monkeypatch):
    cached_jobs = [
        RawJob(
            job_url="https://example.com/cached-workday",
            title="Senior Software Engineer",
            company="Autodesk",
            description="Platform engineering",
            location="Remote",
            site="workday",
            date_posted=None,
        )
    ]
    monkeypatch.setattr(
        workday,
        "_WORKDAY_COMPANIES",
        [
            {
                "company": "Autodesk",
                "slug": "autodesk",
                "host": "autodesk.wd1.myworkdayjobs.com",
                "tenant": "autodesk",
                "site": "Ext",
                "base_url": "https://autodesk.wd1.myworkdayjobs.com/Ext",
            }
        ],
    )
    monkeypatch.setattr(workday, "load_cached_jobs", AsyncMock(return_value=cached_jobs))
    monkeypatch.setattr(workday, "_fetch_company_jobs", AsyncMock(side_effect=AssertionError("cache miss")))

    results = await workday.search(
        [SearchQuery(term="Software Engineer", location="", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == ["https://example.com/cached-workday"]
