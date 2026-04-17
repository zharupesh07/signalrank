import logging
from unittest.mock import AsyncMock

import httpx
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
    assert ("BrowserStack", "browserstack", "browserstack", "External") not in companies


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
async def test_fetch_query_page_converts_expected_http_status():
    request = httpx.Request("POST", "https://example.com/jobs")
    response = httpx.Response(400, request=request)

    class _Client:
        async def post(self, *_args, **_kwargs):
            return response

    with pytest.raises(workday.WorkdayListHTTPError) as exc_info:
        await workday._fetch_query_page(
            _Client(),
            {
                "company": "Aptiv",
                "host": "aptiv.wd5.myworkdayjobs.com",
                "tenant": "aptiv",
                "site": "APTIV_CAREERS",
            },
            SearchQuery(term="MLOps Engineer", location="Pune", country="India"),
            limit=20,
            offset=0,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.company == "Aptiv"


@pytest.mark.asyncio
async def test_workday_search_logs_expected_http_status_once(monkeypatch, caplog):
    monkeypatch.setattr(
        workday,
        "_WORKDAY_COMPANIES",
        [
            {
                "company": "Aptiv",
                "slug": "aptiv",
                "host": "aptiv.wd5.myworkdayjobs.com",
                "tenant": "aptiv",
                "site": "APTIV_CAREERS",
                "base_url": "https://aptiv.wd5.myworkdayjobs.com/APTIV_CAREERS",
            }
        ],
    )
    monkeypatch.setattr(workday, "load_cached_jobs", AsyncMock(return_value=None))
    fetch = AsyncMock(side_effect=workday.WorkdayListHTTPError("Aptiv", "MLOps Engineer", 400))
    monkeypatch.setattr(workday, "_fetch_company_jobs", fetch)

    queries = [
        SearchQuery(term="MLOps Engineer", location="Pune", country="India"),
        SearchQuery(term="Platform Engineer", location="Pune", country="India"),
    ]
    with caplog.at_level(logging.WARNING):
        results = await workday.search(queries, ScraperConfig(), db=None)

    assert results == []
    assert fetch.await_count == 1
    assert "Workday source unavailable for Aptiv: HTTP 400" in caplog.text
    assert "Traceback" not in caplog.text


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
