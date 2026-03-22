import pytest
from unittest.mock import AsyncMock, patch

from batch.scraper import scrape, ScraperConfig, RawJob, _is_blocked
from batch.query_builder import SearchQuery


@pytest.fixture
def config():
    return ScraperConfig()


@pytest.fixture
def queries():
    return [SearchQuery(term="ML Engineer", location="India", country="India")]


def _make_job(url: str, desc: str = "A" * 30) -> RawJob:
    return RawJob(job_url=url, title="Test", company="Co", description=desc, location="X", site="test", date_posted=None)


def test_is_blocked():
    assert not _is_blocked("ML Engineer", [])
    assert _is_blocked("QA Tester Lead", ["qa", "tester"])
    assert not _is_blocked("ML Engineer", ["qa", "tester"])
    assert not _is_blocked(None, ["qa"])
    assert not _is_blocked("Engineer", [])


@pytest.mark.asyncio
async def test_progress_callback(config, queries):
    progress_calls = []

    async def on_progress(**kwargs):
        progress_calls.append(kwargs)

    with patch("batch.sources.rapidapi.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config, on_progress=on_progress)

    assert len(progress_calls) == 2
    assert progress_calls[0]["phase"] == "jobspy"
    assert progress_calls[0]["phase_num"] == 1
    assert progress_calls[1]["phase"] == "parallel"
    assert progress_calls[1]["phase_num"] == 2
    assert result == []


@pytest.mark.asyncio
async def test_scrape_dedup_and_filter(config, queries):
    mock_jobs = [
        _make_job("https://example.com/1"),
        _make_job("https://example.com/1"),  # duplicate
        _make_job("https://example.com/2", desc="short"),  # too short
        _make_job("https://example.com/3"),
    ]

    with patch("batch.sources.rapidapi.search", new_callable=AsyncMock, return_value=mock_jobs), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config)

    urls = [j.job_url for j in result]
    assert "https://example.com/1" in urls
    assert "https://example.com/3" in urls
    assert "https://example.com/2" not in urls  # filtered (short desc)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_scrape_blocklist(queries):
    config = ScraperConfig(title_blocklist=["qa", "tester"])
    mock_jobs = [
        _make_job("https://example.com/1"),
        RawJob(job_url="https://example.com/blocked", title="QA Lead", company="Co",
               description="A" * 30, location="X", site="test", date_posted=None),
    ]

    with patch("batch.sources.rapidapi.search", new_callable=AsyncMock, return_value=mock_jobs), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config)

    assert len(result) == 1
    assert result[0].job_url == "https://example.com/1"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    monkeypatch.setenv("SCRAPER_MAX_RESULTS", "10")
    cfg = ScraperConfig.from_env(title_blocklist=["qa"])
    assert cfg.rapidapi_key == "test-key"
    assert cfg.max_results_per_query == 10
    assert cfg.title_blocklist == ["qa"]
