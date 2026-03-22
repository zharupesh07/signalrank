from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from batch.sources.free_apis import _fetch_himalayas, _fetch_remotive, _fetch_jobicy, search
from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig


def _mock_response(json_data: dict, status_code: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def query():
    return SearchQuery(term="ML Engineer", location="", country="India")


@pytest.mark.asyncio
async def test_fetch_himalayas_filters_by_term(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"title": "ML Engineer at Acme", "companyName": "Acme",
             "description": "Great role", "applicationLink": "https://acme.com/1"},
            {"title": "HR Manager", "companyName": "Corp",
             "description": "HR stuff", "applicationLink": "https://corp.com/2"},
        ]
    })
    jobs = await _fetch_himalayas(client, query)
    assert len(jobs) == 1
    assert jobs[0].title == "ML Engineer at Acme"
    assert jobs[0].site == "himalayas"


@pytest.mark.asyncio
async def test_fetch_himalayas_fallback_url(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"title": "ml engineer", "companyName": "Co", "description": "desc",
             "slug": "ml-engineer-co"},
        ]
    })
    jobs = await _fetch_himalayas(client, query)
    assert len(jobs) == 1
    assert "himalayas.app/jobs/ml-engineer-co" in jobs[0].job_url


@pytest.mark.asyncio
async def test_fetch_himalayas_handles_error(query):
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("timeout")
    jobs = await _fetch_himalayas(client, query)
    assert jobs == []


@pytest.mark.asyncio
async def test_fetch_remotive_returns_jobs(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"url": "https://remotive.com/j/1", "title": "ML Engineer",
             "company_name": "Remote Co", "description": "Cool job",
             "candidate_required_location": "Worldwide"},
        ]
    })
    jobs = await _fetch_remotive(client, query)
    assert len(jobs) == 1
    assert jobs[0].site == "remotive"
    assert jobs[0].location == "Worldwide"


@pytest.mark.asyncio
async def test_fetch_remotive_skips_missing_url(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"title": "No URL Job", "company_name": "Co", "description": "desc"},
        ]
    })
    jobs = await _fetch_remotive(client, query)
    assert jobs == []


@pytest.mark.asyncio
async def test_fetch_remotive_handles_error(query):
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("timeout")
    jobs = await _fetch_remotive(client, query)
    assert jobs == []


@pytest.mark.asyncio
async def test_fetch_jobicy_returns_jobs(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"url": "https://jobicy.com/j/1", "jobTitle": "ML Engineer",
             "companyName": "Jobicy Co", "jobDescription": "Remote ML job",
             "jobGeo": "Worldwide"},
        ]
    })
    jobs = await _fetch_jobicy(client, query)
    assert len(jobs) == 1
    assert jobs[0].site == "jobicy"
    assert jobs[0].company == "Jobicy Co"


@pytest.mark.asyncio
async def test_fetch_jobicy_default_location(query):
    client = AsyncMock()
    client.get.return_value = _mock_response({
        "jobs": [
            {"url": "https://jobicy.com/j/2", "jobTitle": "Engineer",
             "companyName": "Co", "jobDescription": "desc", "jobGeo": None},
        ]
    })
    jobs = await _fetch_jobicy(client, query)
    assert jobs[0].location == "Remote"


@pytest.mark.asyncio
async def test_search_only_processes_first_5_queries():
    queries = [SearchQuery(term=f"Role {i}", location="", country="India") for i in range(10)]
    config = ScraperConfig()

    call_count = 0

    async def mock_himalayas(client, query):
        nonlocal call_count
        call_count += 1
        return []

    with patch("batch.sources.free_apis._fetch_himalayas", side_effect=mock_himalayas), \
         patch("batch.sources.free_apis._fetch_remotive", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis._fetch_jobicy", new_callable=AsyncMock, return_value=[]):
        await search(queries, config)

    assert call_count == 5
