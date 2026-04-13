import pytest
from unittest.mock import AsyncMock, patch

from api.models import JobRaw
from batch.scrape_cache import store_cached_jobs
from batch.scraper import plan_incremental_scrape, scrape, ScraperConfig, RawJob, _is_blocked
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
         patch("batch.sources.ats_direct.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config, on_progress=on_progress)

    phases = [c["phase"] for c in progress_calls]
    assert "jobspy_indeed" in phases
    assert "parallel" in phases
    assert result == []


@pytest.mark.asyncio
async def test_scrape_dedup_and_filter(config, queries):
    mock_jobs = [
        _make_job("https://example.com/1"),
        _make_job("https://example.com/1"),  # duplicate
        _make_job("https://example.com/2"),
        _make_job("https://example.com/3"),
    ]

    with patch("batch.sources.rapidapi.search", new_callable=AsyncMock, return_value=mock_jobs), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.ats_direct.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config)

    urls = [j.job_url for j in result]
    assert "https://example.com/1" in urls
    assert "https://example.com/2" in urls
    assert "https://example.com/3" in urls
    assert len(result) == 3


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
         patch("batch.sources.ats_direct.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config)

    assert len(result) == 1
    assert result[0].job_url == "https://example.com/1"


@pytest.mark.asyncio
async def test_scrape_can_return_urls_only(config, queries):
    mock_jobs = [
        _make_job("https://example.com/1"),
        _make_job("https://example.com/2"),
    ]

    with patch("batch.sources.rapidapi.search", new_callable=AsyncMock, return_value=mock_jobs), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.ats_direct.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.free_apis.search", new_callable=AsyncMock, return_value=[]), \
         patch("batch.sources.google_jobs.search", new_callable=AsyncMock, return_value=[]):
        result = await scrape(queries, config, return_mode="urls")

    assert result == ["https://example.com/1", "https://example.com/2"]


def test_config_from_env(monkeypatch):
    import api.config as _cfg_mod
    monkeypatch.setattr(_cfg_mod.settings, "rapidapi_key", "test-key")
    monkeypatch.setattr(_cfg_mod.settings, "scraper_max_results", 10)
    cfg = ScraperConfig.from_env(title_blocklist=["qa"])
    assert cfg.rapidapi_key == "test-key"
    assert cfg.max_results_per_query == 10
    assert cfg.title_blocklist == ["qa"]


@pytest.mark.asyncio
async def test_scrape_reuses_jobspy_cache_across_calls(db):
    queries = [SearchQuery(term="SAP SD Consultant", location="", country="India")]
    config = ScraperConfig(sources=["indeed"], hours_old=24)
    scraped_jobs = [
        _make_job("https://example.com/cache-1"),
        _make_job("https://example.com/cache-2"),
    ]

    async def on_persist(jobs):
        for job in jobs:
            db.add(
                JobRaw(
                    job_url=job.job_url,
                    title=job.title,
                    company=job.company,
                    description=job.description,
                    location=job.location,
                    site=job.site,
                    date_posted=job.date_posted,
                )
            )
        await db.commit()

    with patch("batch.sources.jobspy_source._scrape_sync", return_value=scraped_jobs) as mock_scrape:
        first = await scrape(queries, config, on_persist=on_persist, db=db)
    assert mock_scrape.call_count == 1
    assert [job.job_url for job in first] == [job.job_url for job in scraped_jobs]

    with patch("batch.sources.jobspy_source._scrape_sync", side_effect=AssertionError("cache miss")):
        second = await scrape(queries, config, db=db)
    assert [job.job_url for job in second] == [job.job_url for job in scraped_jobs]


@pytest.mark.asyncio
async def test_plan_incremental_scrape_reuses_fresh_indeed_query_cache(db):
    queries = [SearchQuery(term="MLOps Engineer", location="Bangalore", country="India")]
    config = ScraperConfig(sources=["indeed"], hours_old=24)

    db.add(
        JobRaw(
            job_url="https://example.com/cached-indeed",
            title="MLOps Engineer",
            company="Acme",
            description="Cached description",
            location="Bangalore",
            site="indeed",
        )
    )
    await db.commit()

    await store_cached_jobs(
        db,
        provider="jobspy",
        site="indeed",
        query=queries[0],
        config=config,
        jobs=[
            RawJob(
                job_url="https://example.com/cached-indeed",
                title="MLOps Engineer",
                company="Acme",
                description="Cached description",
                location="Bangalore",
                site="indeed",
                date_posted=None,
            )
        ],
    )

    stale_queries, cached_urls = await plan_incremental_scrape(queries, config, db)

    assert stale_queries == []
    assert cached_urls == ["https://example.com/cached-indeed"]


@pytest.mark.asyncio
async def test_plan_incremental_scrape_marks_query_stale_when_cache_missing(db):
    queries = [
        SearchQuery(term="MLOps Engineer", location="Bangalore", country="India"),
        SearchQuery(term="AI Platform Engineer", location="Pune", country="India"),
    ]
    config = ScraperConfig(sources=["indeed"], hours_old=24)

    db.add(
        JobRaw(
            job_url="https://example.com/cached-indeed",
            title="MLOps Engineer",
            company="Acme",
            description="Cached description",
            location="Bangalore",
            site="indeed",
        )
    )
    await db.commit()

    await store_cached_jobs(
        db,
        provider="jobspy",
        site="indeed",
        query=queries[0],
        config=config,
        jobs=[
            RawJob(
                job_url="https://example.com/cached-indeed",
                title="MLOps Engineer",
                company="Acme",
                description="Cached description",
                location="Bangalore",
                site="indeed",
                date_posted=None,
            )
        ],
    )

    stale_queries, cached_urls = await plan_incremental_scrape(queries, config, db)

    assert stale_queries == [queries[1]]
    assert cached_urls == ["https://example.com/cached-indeed"]


@pytest.mark.asyncio
async def test_scrape_cache_is_scoped_by_hours_old(db):
    queries = [SearchQuery(term="SAP SD Consultant", location="", country="India")]
    first_jobs = [_make_job("https://example.com/hours-24")]
    second_jobs = [_make_job("https://example.com/hours-48")]

    async def on_persist(jobs):
        for job in jobs:
            db.add(
                JobRaw(
                    job_url=job.job_url,
                    title=job.title,
                    company=job.company,
                    description=job.description,
                    location=job.location,
                    site=job.site,
                    date_posted=job.date_posted,
                )
            )
        await db.commit()

    with patch("batch.sources.jobspy_source._scrape_sync", return_value=first_jobs) as first_scrape:
        result_24 = await scrape(queries, ScraperConfig(sources=["indeed"], hours_old=24), on_persist=on_persist, db=db)
    assert first_scrape.call_count == 1
    assert [job.job_url for job in result_24] == ["https://example.com/hours-24"]

    with patch("batch.sources.jobspy_source._scrape_sync", return_value=second_jobs) as second_scrape:
        result_48 = await scrape(queries, ScraperConfig(sources=["indeed"], hours_old=48), on_persist=on_persist, db=db)
    assert second_scrape.call_count == 1
    assert [job.job_url for job in result_48] == ["https://example.com/hours-48"]


@pytest.mark.asyncio
async def test_google_jobs_results_are_cached_across_calls(db):
    queries = [SearchQuery(term="ML Engineer", location="Pune", country="India")]
    config = ScraperConfig(sources=["google_jobs"], hours_old=24)
    cached_jobs = [_make_job("https://example.com/google-cache")]

    async def on_persist(jobs):
        for job in jobs:
            db.add(
                JobRaw(
                    job_url=job.job_url,
                    title=job.title,
                    company=job.company,
                    description=job.description,
                    location=job.location,
                    site=job.site,
                    date_posted=job.date_posted,
                )
            )
        await db.commit()

    with patch("batch.sources.google_jobs._scrape_sync", return_value=cached_jobs) as mock_scrape:
        first = await scrape(queries, config, on_persist=on_persist, db=db)
    assert mock_scrape.call_count == 1
    assert [job.job_url for job in first] == [job.job_url for job in cached_jobs]

    with patch("batch.sources.google_jobs._scrape_sync", side_effect=AssertionError("cache miss")):
        second = await scrape(queries, config, db=db)
    assert [job.job_url for job in second] == [job.job_url for job in cached_jobs]


@pytest.mark.asyncio
async def test_rapidapi_results_are_cached_across_calls(db, monkeypatch):
    queries = [SearchQuery(term="ML Engineer", location="Pune", country="India")]
    config = ScraperConfig(sources=["rapidapi"], hours_old=24, rapidapi_key="test-key")
    cached_jobs = [_make_job("https://example.com/rapidapi-cache")]

    async def on_persist(jobs):
        for job in jobs:
            db.add(
                JobRaw(
                    job_url=job.job_url,
                    title=job.title,
                    company=job.company,
                    description=job.description,
                    location=job.location,
                    site=job.site,
                    date_posted=job.date_posted,
                )
            )
        await db.commit()

    async def fake_fetch(*args, **kwargs):
        return cached_jobs

    monkeypatch.setattr("batch.sources.rapidapi._fetch_source", AsyncMock(side_effect=fake_fetch))

    first = await scrape(queries, config, on_persist=on_persist, db=db)
    assert [job.job_url for job in first] == [job.job_url for job in cached_jobs]

    with patch("batch.sources.rapidapi._fetch_source", side_effect=AssertionError("cache miss")):
        second = await scrape(queries, config, db=db)
    assert [job.job_url for job in second] == [job.job_url for job in cached_jobs]


@pytest.mark.asyncio
async def test_parallel_sources_use_isolated_db_sessions(db, queries):
    config = ScraperConfig(sources=["rapidapi", "free_apis", "google_jobs"])
    seen_db_ids = {}

    async def _rapidapi(*args, db=None, **kwargs):
        seen_db_ids["rapidapi"] = id(db)
        return []

    async def _free_apis(*args, db=None, **kwargs):
        seen_db_ids["free_apis"] = id(db)
        return []

    async def _google_jobs(*args, db=None, **kwargs):
        seen_db_ids["google_jobs"] = id(db)
        return []

    with patch("batch.sources.rapidapi.search", new=_rapidapi), \
         patch("batch.sources.free_apis.search", new=_free_apis), \
         patch("batch.sources.google_jobs.search", new=_google_jobs), \
         patch("batch.sources.jobspy_source.search", new_callable=AsyncMock, return_value=[]):
        await scrape(queries, config, db=db)

    assert len(seen_db_ids) == 3
    assert all(db_id != id(db) for db_id in seen_db_ids.values())
    assert len(set(seen_db_ids.values())) == 3
