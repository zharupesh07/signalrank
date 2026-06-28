"""Ingest smoke test — does the scrape pipe fill from this (cloud) IP?

Calls signalrank's own JobSpy source directly (no parallel code path), pulls a
small batch for one title across LinkedIn + Google, US / last 24h, and prints
what came back. No DB writes, no scoring, no email — just proves ingestion works.

Run from backend/:  python -m jobdigest.smoke_ingest
"""
from __future__ import annotations

import asyncio
import logging

from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig
from batch.sources import jobspy_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# One title to keep it fast; LinkedIn is ~80s/query so we cap hard.
QUERIES = [SearchQuery(term="Asic Engineer or Clock", location="United States", country="USA")]
SITES = ["google", "linkedin"]  # google first (fast), linkedin second (slow)


def _make_config() -> ScraperConfig:
    return ScraperConfig(
        hours_old=24,
        default_country="USA",
        max_results_per_query=25,   # small batch for a smoke test
        linkedin_max_queries=1,     # IMPORTANT: 0 disables LinkedIn entirely
        sources=SITES,
        jobspy_delay=1.0,
        jobspy_timeout=120,
        total_timeout=300,
    )


async def main() -> None:
    config = _make_config()
    grand_total = 0
    for site in SITES:
        print(f"\n=== scraping {site} for '{QUERIES[0].term}' (US, 24h) ===")
        try:
            jobs = await jobspy_source.search(QUERIES, config, site=site, db=None)
        except Exception as exc:  # noqa: BLE001 — smoke test, surface anything
            print(f"  {site}: ERROR — {type(exc).__name__}: {exc}")
            continue
        grand_total += len(jobs)
        print(f"  {site}: {len(jobs)} jobs")
        for j in jobs[:5]:
            posted = j.date_posted.date() if j.date_posted else "?"
            print(f"    • {j.title}  @ {j.company}  [{j.location}]  {posted}")
            print(f"      {j.job_url}")

    print(f"\n=== TOTAL: {grand_total} jobs ===")
    if grand_total == 0:
        print("No jobs returned. Likely causes: cloud-IP rate-limiting (esp. LinkedIn),"
              " or no postings in the last 24h for this exact title. Not necessarily a bug.")


if __name__ == "__main__":
    asyncio.run(main())