from unittest.mock import AsyncMock
from urllib.parse import urlparse

import base64
import json
import pytest

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig
from batch.sources import swiggy


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(swiggy.asyncio, "sleep", _noop)


def test_swiggy_job_url_encodes_req_id():
    url = swiggy._job_url(25996)
    parsed = urlparse(url)
    raw_p = parsed.query.split("p=", 1)[1]
    payload = json.loads(base64.b64decode(raw_p).decode("utf-8"))

    assert parsed.scheme == "https"
    assert parsed.netloc == "swiggy.mynexthire.com"
    assert payload["pageType"] == "jd"
    assert payload["reqId"] == 25996


def test_swiggy_matches_query_uses_tokens_and_location():
    job = {
        "reqTitle": "Lead AI Platform Engineer",
        "jdDisplay": "Build agentic systems and ML infrastructure",
        "location": "Bangalore",
        "locationAddress": "Bangalore",
        "buName": "Swiggy",
    }

    assert swiggy._matches_query(job, SearchQuery(term="AI Platform Engineer", location="Bangalore", country="India"))
    assert not swiggy._matches_query(job, SearchQuery(term="finance", location="Bangalore", country="India"))


@pytest.mark.asyncio
async def test_swiggy_search_fetches_and_caches(monkeypatch):
    cached = [RawJob(
        job_url="https://swiggy.mynexthire.com/employer/jobs/careers?src=careers&p=abc",
        title="Lead AI Platform Engineer",
        company="Swiggy",
        description="Build agentic systems",
        location="Bangalore",
        site="mynexthire",
        date_posted=None,
    )]
    monkeypatch.setattr(swiggy, "load_cached_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr(swiggy, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(swiggy, "_fetch_jobs", AsyncMock(return_value=cached))

    results = await swiggy.search(
        [SearchQuery(term="agentic systems", location="Bangalore", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == [cached[0].job_url]
