"""Scrape a LinkedIn jobs search-results page.

Usage:
    cd signalrank/backend
    set -a && source .env && set +a
    uv run python -m tools.scrape_linkedin_search --url "https://www.linkedin.com/jobs/search-results/?keywords=agentic%20ai"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from batch.scraper import ScraperConfig
from batch.sources.linkedin_page import scrape_url


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="LinkedIn jobs search URL")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    config = ScraperConfig(
        linkedin_cookie_header=os.environ.get("LINKEDIN_COOKIE_HEADER", ""),
    )
    jobs = await scrape_url(args.url, config)
    print(json.dumps([job.__dict__ for job in jobs], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
