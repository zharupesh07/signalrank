from unittest.mock import AsyncMock

import pytest

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig
from batch.sources import amazon_jobs


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(amazon_jobs.asyncio, "sleep", _noop)


def test_amazon_url_builder_uses_offset_and_terms():
    url = amazon_jobs._search_url(SearchQuery(term="machine learning", location="India", country="India"), 20)

    assert url.startswith("https://www.amazon.jobs/en/search.json?")
    assert "base_query=machine+learning" in url
    assert "loc_query=India" in url
    assert "offset=20" in url


def test_amazon_normalizes_job_and_matches_query():
    job = {
        "title": "Machine Learning Engineer",
        "company_name": "Amazon Data Services, Inc.",
        "description_short": "Build agentic AI systems",
        "basic_qualifications": "Python and distributed systems",
        "preferred_qualifications": "ML platform",
        "job_path": "/en/jobs/1234/machine-learning-engineer",
        "normalized_location": "Bengaluru, Karnataka, India",
        "posted_date": "January 27, 2026",
    }

    normalized = amazon_jobs._normalize_job(job)
    assert normalized is not None
    assert normalized.job_url == "https://www.amazon.jobs/en/jobs/1234/machine-learning-engineer"
    assert normalized.company == "Amazon Data Services, Inc."
    assert amazon_jobs._matches_query(job, SearchQuery(term="machine learning", location="India", country="India"))
    assert not amazon_jobs._matches_query(job, SearchQuery(term="finance", location="India", country="India"))


@pytest.mark.asyncio
async def test_amazon_search_fetches_and_caches(monkeypatch):
    cached = [RawJob(
        job_url="https://www.amazon.jobs/en/jobs/1/example",
        title="ML Engineer",
        company="Amazon",
        description="Build ML systems",
        location="Bangalore, India",
        site="amazon",
        date_posted=None,
    )]
    monkeypatch.setattr(amazon_jobs, "load_cached_jobs", AsyncMock(return_value=None))
    monkeypatch.setattr(amazon_jobs, "store_cached_jobs", AsyncMock())
    monkeypatch.setattr(amazon_jobs, "_fetch_jobs", AsyncMock(return_value=cached))

    results = await amazon_jobs.search(
        [SearchQuery(term="ML Engineer", location="India", country="India")],
        ScraperConfig(),
        db=None,
    )

    assert [job.job_url for job in results] == [cached[0].job_url]
