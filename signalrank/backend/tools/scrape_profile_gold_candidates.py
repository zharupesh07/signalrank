from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from tools import build_curated_profile_gold
from tools import build_profile_eval_sets
from tools import hybrid_match_eval as hybrid
from tools import rank_resume_existing_corpus

DEFAULT_OUTPUT_ROOT = (
    Path(__file__).resolve().parents[1] / "tmp" / "resume_existing_corpus_rank"
)


def _locations(
    candidate_profile: dict, explicit_locations: list[str] | None
) -> list[str]:
    if explicit_locations:
        return explicit_locations
    values = []
    for item in candidate_profile.get("preferred_locations") or []:
        value = str(item or "").strip()
        if value and value.lower() not in {"india", "in"}:
            values.append(value)
    values.append("Remote")
    return build_profile_eval_sets._dedupe(values, limit=3) or ["Remote"]


async def _scrape_profile(profile: str, args: argparse.Namespace) -> dict:
    candidate_profile, _resume_text = build_profile_eval_sets.build_profile(profile)
    policy = hybrid._build_match_policy(candidate_profile)
    terms = build_curated_profile_gold.build_scrape_terms(
        candidate_profile,
        policy,
        limit=args.term_limit,
    )
    locations = _locations(candidate_profile, args.location)
    resume_path = (
        build_profile_eval_sets.RESUMES_DIR
        / build_profile_eval_sets.PROFILE_FILES[profile]
    )
    label = args.label or f"{profile}-{args.jobspy_hours_old // 24}d-gold-candidates"
    run_args = argparse.Namespace(
        analysis_k=args.analysis_k,
        jobspy_hours_old=args.jobspy_hours_old,
        jobspy_locations=locations,
        jobspy_max_results_per_query=args.jobspy_max_results_per_query,
        jobspy_terms=terms,
        label=label,
        llm_verify_model=rank_resume_existing_corpus.FAST_MODELS[0],
        llm_verify_top=0,
        output_dir=args.output_dir,
        resume=str(resume_path),
        scrape_jobspy=True,
        top_k=args.top_k,
    )
    report = await rank_resume_existing_corpus._run_for_resume(resume_path, run_args)
    output_root = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT
    )
    out_dir = (
        output_root
        / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{rank_resume_existing_corpus._slugify(label)}-standalone"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "jobspy_scrape_report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    (out_dir / "summary.md").write_text(
        rank_resume_existing_corpus._render_summary(label, report, args.analysis_k)
    )
    return {
        "locations": locations,
        "output_dir": str(out_dir),
        "profile": profile,
        "ranked_jobs": report["ranked_jobs"],
        "scraped_jobs": report["scraped_jobs"],
        "terms": terms,
    }


async def _async_main() -> None:
    args = _build_parser().parse_args()
    profiles = args.profile or sorted(build_profile_eval_sets.PROFILE_FILES)
    results = [await _scrape_profile(profile, args) for profile in profiles]
    print(json.dumps({"profiles": results}, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape JobSpy candidates using profile-derived policy terms"
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(build_profile_eval_sets.PROFILE_FILES),
    )
    parser.add_argument("--location", action="append")
    parser.add_argument("--jobspy-hours-old", type=int, default=1440)
    parser.add_argument("--jobspy-max-results-per-query", type=int, default=40)
    parser.add_argument("--term-limit", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--analysis-k", type=int, default=50)
    parser.add_argument("--label")
    parser.add_argument("--output-dir")
    return parser


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
