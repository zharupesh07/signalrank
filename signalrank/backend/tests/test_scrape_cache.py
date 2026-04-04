from sqlalchemy import select, text

from api.database import ensure_runtime_schema_compatibility
from api.models import ScrapeQueryCache
from batch.query_builder import SearchQuery
from batch.scrape_cache import store_cached_jobs
from batch.scraper import RawJob, ScraperConfig


async def test_store_cached_jobs_upserts_against_runtime_compat_unique_index(test_engine, db):
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS scrape_query_cache"))

    await ensure_runtime_schema_compatibility(test_engine)

    query = SearchQuery(term="SAP SD Consultant", location="", country="India")
    config = ScraperConfig(hours_old=24)

    await store_cached_jobs(
        db,
        provider="jobspy",
        site="indeed",
        query=query,
        config=config,
        jobs=[
            RawJob(
                job_url="https://example.com/jobs/1",
                title="SAP SD Consultant",
                company="Acme",
                description=None,
                location="Remote",
                site="indeed",
                date_posted=None,
            )
        ],
    )
    await store_cached_jobs(
        db,
        provider="jobspy",
        site="indeed",
        query=query,
        config=config,
        jobs=[
            RawJob(
                job_url="https://example.com/jobs/2",
                title="Senior SAP SD Consultant",
                company="Acme",
                description=None,
                location="Remote",
                site="indeed",
                date_posted=None,
            )
        ],
    )

    rows = (await db.execute(select(ScrapeQueryCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].result_job_urls == ["https://example.com/jobs/2"]
    assert rows[0].result_count == 1
