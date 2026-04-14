from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from batch.context import build_context
from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig, raw_job_to_dict, scrape
from domain.company import CompanyScorer
from ranking.profile_fresh_rank import (
    DEFAULT_LOCATIONS,
    DEFAULT_QUERY_TERMS,
    rank_profile_fresh_jobs,
    select_top_companies,
    summarize_profile_fresh_run,
)

logger = logging.getLogger(__name__)

DEFAULT_RESUME_PATH = Path(__file__).resolve().parents[1] / "data" / "resume_example.yaml"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "tmp" / "top100_company_rank_300" / "top100_companies_profile_fresh.csv"
DEFAULT_SOURCES = [
    "ats_direct",
    "company_portals",
    "amazon_jobs",
    "google_jobs",
    "free_apis",
    "rapidapi",
]


def _read_resume_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _build_queries(terms: list[str], locations: list[str], country: str) -> list[SearchQuery]:
    queries: list[SearchQuery] = []
    seen: set[tuple[str, str, str]] = set()
    for term in terms:
        for location in locations:
            key = (term.lower(), location.lower(), country.lower())
            if key in seen:
                continue
            seen.add(key)
            queries.append(SearchQuery(term=term, location=location, country=country))
    return queries


def _serialize_job(job) -> dict:
    payload = raw_job_to_dict(job)
    if payload.get("date_posted") is not None:
        payload["date_posted"] = payload["date_posted"].isoformat()
    return payload


async def generate_profile_fresh_company_rank(
    *,
    resume_path: Path | None = None,
    resume_text: str | None = None,
    output_csv: Path,
    limit: int,
    country: str,
    terms: list[str],
    locations: list[str],
    sources: list[str],
    companies: list[str] | None = None,
) -> dict:
    effective_resume_text = resume_text if resume_text is not None else _read_resume_text(resume_path or DEFAULT_RESUME_PATH)
    cfg = build_context(user_id="__profile_fresh__", resume_text=effective_resume_text).config
    company_scorer = CompanyScorer(cfg)
    scraper_cfg = ScraperConfig.from_env()
    scraper_cfg.hours_old = 14 * 24
    scraper_cfg.sources = sources
    scraper_cfg.default_country = country
    scraper_cfg.company_allowlist = companies or None

    queries = _build_queries(terms, locations, country)
    raw_jobs = await scrape(queries, scraper_cfg, db=None)
    serialized_jobs = [_serialize_job(job) for job in raw_jobs]
    ranked_jobs, rejection_counts = rank_profile_fresh_jobs(
        serialized_jobs,
        company_scorer=company_scorer,
        allowed_companies=companies,
    )
    company_rows = select_top_companies(ranked_jobs, limit=limit)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary_path = output_csv.with_suffix(".summary.json")
    rows = [
        {
            "company_rank": row["company_rank"],
            "company": row["company"],
            "company_tier": row["company_tier"],
            "role_bucket": row["role_bucket"],
            "best_job_title": row["best_job_title"],
            "best_job_location": row["best_job_location"],
            "location_bucket": row["location_bucket"],
            "remote_policy_match": row["remote_policy_match"],
            "yoe_match_band": row["yoe_match_band"],
            "site": row["site"],
            "best_job_url": row["best_job_url"],
            "score": row["score"],
            "jobs_considered_for_company": row["jobs_considered_for_company"],
        }
        for row in company_rows
    ]

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [
            "company_rank",
            "company",
            "company_tier",
            "role_bucket",
            "best_job_title",
            "best_job_location",
            "location_bucket",
            "remote_policy_match",
            "yoe_match_band",
            "site",
            "best_job_url",
            "score",
            "jobs_considered_for_company",
        ])
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize_profile_fresh_run(
        scraped_jobs=len(raw_jobs),
        ranked_jobs=ranked_jobs,
        company_rows=company_rows,
        rejection_counts=rejection_counts,
        sources=sources,
        queries=terms,
    )
    summary.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "resume_path": str(resume_path) if resume_path is not None else None,
            "output_csv": str(output_csv),
            "locations": locations,
            "companies": companies or [],
        }
    )
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)

    return {
        "output_csv": str(output_csv),
        "summary_json": str(summary_path),
        "scraped_jobs": len(raw_jobs),
        "jobs_scored": len(ranked_jobs),
        "companies_exported": len(company_rows),
        "rejection_counts": dict(sorted(Counter(rejection_counts).items())),
        "rows": rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fresh scrape and strict company-level ranking for a target profile")
    parser.add_argument("--resume-path", default=str(DEFAULT_RESUME_PATH))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--country", default="India")
    parser.add_argument("--queries", nargs="*", default=DEFAULT_QUERY_TERMS)
    parser.add_argument("--locations", nargs="*", default=DEFAULT_LOCATIONS)
    parser.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    parser.add_argument("--companies", nargs="*", default=[])
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(
        generate_profile_fresh_company_rank(
            resume_path=Path(args.resume_path),
            resume_text=None,
            output_csv=Path(args.output_csv),
            limit=args.limit,
            country=args.country,
            terms=list(args.queries),
            locations=list(args.locations),
            sources=list(args.sources),
            companies=list(args.companies),
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
