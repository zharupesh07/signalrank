from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from batch.query_builder import SearchQuery
from batch.scraper import RawJob, ScraperConfig

logger = logging.getLogger(__name__)


def _scrape_sync(term: str, location: str, config: ScraperConfig) -> list[RawJob]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.warning("python-jobspy not installed, skipping")
        return []

    try:
        df = scrape_jobs(
            site_name=["indeed", "linkedin"],
            search_term=term,
            location=location,
            results_wanted=config.max_results_per_query,
            hours_old=config.hours_old,
            country_indeed=location,
        )
    except Exception:
        logger.exception("JobSpy scrape failed for %s / %s", term, location)
        return []

    jobs = []
    for _, row in df.iterrows():
        url = str(row.get("job_url", ""))
        if not url:
            continue
        date_posted = None
        raw_date = row.get("date_posted")
        if raw_date is not None:
            try:
                if hasattr(raw_date, "to_pydatetime"):
                    date_posted = raw_date.to_pydatetime()
                    if date_posted.tzinfo is None:
                        date_posted = date_posted.replace(tzinfo=timezone.utc)
                else:
                    date_posted = datetime.fromisoformat(str(raw_date))
            except (ValueError, TypeError):
                pass

        jobs.append(RawJob(
            job_url=url,
            title=str(row.get("title", "")) or None,
            company=str(row.get("company_name", "")) or None,
            description=str(row.get("description", "")) or None,
            location=str(row.get("location", "")) or None,
            site=str(row.get("site", "jobspy")),
            date_posted=date_posted,
        ))
    return jobs


async def search(queries: list[SearchQuery], config: ScraperConfig) -> list[RawJob]:
    all_jobs: list[RawJob] = []
    for query in queries:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_scrape_sync, query.term, query.location, config),
                timeout=180,
            )
            all_jobs.extend(result)
        except asyncio.TimeoutError:
            logger.warning("JobSpy timeout for %s / %s", query.term, query.location)
        except Exception:
            logger.exception("JobSpy failed for %s / %s", query.term, query.location)
        await asyncio.sleep(config.jobspy_delay)
    return all_jobs
