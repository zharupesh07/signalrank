from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from batch.query_builder import build_queries, build_query_plan_debug
from domain.intent_matching import PROFILE_INTENT_KEY
from tools import build_profile_eval_sets
from tools import rank_resume_existing_corpus

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[1] / "tmp" / "scrape_query_planner_live_eval"
)
DEFAULT_PROFILES = ("example", "ayush", "aditya", "vivek")
REJECT_BANDS = {"hard_violation", "reject"}


def _dedupe(values: list[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if limit and len(result) >= limit:
            break
    return result


def _profile_from_key(
    profile_key: str,
    *,
    use_for_scrape: bool,
    default_max_terms: int,
    location_limit: int,
) -> SimpleNamespace:
    candidate_profile, _resume_text = build_profile_eval_sets.build_profile(profile_key)
    intent = candidate_profile.get(PROFILE_INTENT_KEY)
    target_roles = (
        list(intent.get("target_roles") or [])
        if isinstance(intent, dict)
        else list(candidate_profile.get("target_roles_primary") or [])
    )
    locations = _dedupe(
        list(candidate_profile.get("preferred_locations") or ["Remote"]),
        limit=location_limit,
    )
    return SimpleNamespace(
        name=profile_key,
        target_roles=target_roles,
        preferred_locations=locations,
        custom_search_queries=[],
        candidate_profile=candidate_profile,
        config_overrides={
            "scraping": {
                "intent_query_planner": {
                    "shadow_enabled": True,
                    "use_for_scrape": use_for_scrape,
                    "default_max_terms": default_max_terms,
                }
            }
        },
    )


def _query_terms_and_locations(
    profile: Any,
    *,
    max_terms: int,
) -> tuple[list[str], list[str]]:
    queries = build_queries(profile, max_terms=max_terms)
    terms = _dedupe([query.term for query in queries])
    locations = _dedupe(
        [
            query.location or query.country
            for query in queries
            if str(query.location or query.country or "").strip()
        ]
    )
    return terms, locations


def _resume_path(profile_key: str) -> Path:
    return (
        build_profile_eval_sets.RESUMES_DIR
        / build_profile_eval_sets.PROFILE_FILES[profile_key]
    )


def _top_jobs(
    report: dict[str, Any], approach_name: str, limit: int
) -> list[dict[str, Any]]:
    for approach in report.get("approaches") or []:
        if approach.get("approach") == approach_name:
            return list(approach.get("top_jobs") or [])[:limit]
    return []


def _fit_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(job.get("fit_band") or "unknown") for job in jobs))


def _is_non_reject(job: dict[str, Any]) -> bool:
    return str(job.get("fit_band") or "").strip() not in REJECT_BANDS


def _job_key(job: dict[str, Any]) -> str:
    return str(job.get("job_url") or job.get("id") or "").strip()


def _job_label(job: dict[str, Any]) -> str:
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    score = float(job.get("final_score") or 0.0)
    band = str(job.get("fit_band") or "")
    return f"{title} | {company} | {band} | {score:.2f}"


def _compare_reports(
    current_report: dict[str, Any],
    intent_report: dict[str, Any],
    *,
    approach_name: str,
    top_k: int,
    min_non_reject_top: int,
    max_reject_rate: float,
) -> dict[str, Any]:
    current_jobs = _top_jobs(current_report, approach_name, top_k)
    intent_jobs = _top_jobs(intent_report, approach_name, top_k)
    current_urls = {_job_key(job) for job in current_jobs if _job_key(job)}
    intent_urls = {_job_key(job) for job in intent_jobs if _job_key(job)}
    overlap = current_urls & intent_urls
    new_intent_jobs = [
        job for job in intent_jobs if _job_key(job) and _job_key(job) not in overlap
    ]
    lost_current_jobs = [
        job for job in current_jobs if _job_key(job) and _job_key(job) not in overlap
    ]
    current_non_reject_count = sum(1 for job in current_jobs if _is_non_reject(job))
    intent_reject_count = sum(1 for job in intent_jobs if not _is_non_reject(job))
    intent_non_reject_count = len(intent_jobs) - intent_reject_count
    intent_reject_rate = (
        round(intent_reject_count / len(intent_jobs), 3) if intent_jobs else 1.0
    )
    checks = {
        "intent_has_ranked_jobs": bool(intent_jobs),
        "intent_has_non_reject_top": intent_non_reject_count >= min_non_reject_top,
        "intent_reject_rate_ok": intent_reject_rate <= max_reject_rate,
        "current_non_reject_not_regressed": (
            intent_non_reject_count >= current_non_reject_count
        ),
    }
    return {
        "approach": approach_name,
        "passes": all(checks.values()),
        "checks": checks,
        "current_top_count": len(current_jobs),
        "intent_top_count": len(intent_jobs),
        "top_overlap_count": len(overlap),
        "top_overlap_rate": round(len(overlap) / max(len(current_urls), 1), 3),
        "current_non_reject_top_count": current_non_reject_count,
        "intent_non_reject_top_count": intent_non_reject_count,
        "intent_reject_rate": intent_reject_rate,
        "current_fit_counts": _fit_counts(current_jobs),
        "intent_fit_counts": _fit_counts(intent_jobs),
        "new_intent_top": [_job_label(job) for job in new_intent_jobs[:10]],
        "lost_current_top": [_job_label(job) for job in lost_current_jobs[:10]],
    }


async def _run_variant(
    *,
    profile_key: str,
    label: str,
    terms: list[str],
    locations: list[str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_args = argparse.Namespace(
        analysis_k=args.analysis_k,
        jobspy_hours_old=args.days * 24,
        jobspy_locations=locations,
        jobspy_max_results_per_query=args.max_results_per_query,
        jobspy_terms=terms,
        label=label,
        llm_verify_model=rank_resume_existing_corpus.FAST_MODELS[0],
        llm_verify_top=0,
        output_dir=args.output_dir,
        resume=str(_resume_path(profile_key)),
        scrape_jobspy=True,
        top_k=args.top_k,
    )
    return await rank_resume_existing_corpus._run_for_resume(
        _resume_path(profile_key), run_args
    )


async def _run_profile(profile_key: str, args: argparse.Namespace) -> dict[str, Any]:
    current_profile = _profile_from_key(
        profile_key,
        use_for_scrape=False,
        default_max_terms=args.intent_term_limit,
        location_limit=args.location_limit,
    )
    intent_profile = _profile_from_key(
        profile_key,
        use_for_scrape=True,
        default_max_terms=args.intent_term_limit,
        location_limit=args.location_limit,
    )
    _, candidate_text = build_profile_eval_sets.build_profile(profile_key)
    current_terms, current_locations = _query_terms_and_locations(
        current_profile,
        max_terms=args.current_term_limit,
    )
    intent_terms, intent_locations = _query_terms_and_locations(
        intent_profile,
        max_terms=args.intent_term_limit,
    )
    if args.location:
        current_locations = args.location[: args.location_limit]
        intent_locations = args.location[: args.location_limit]
    else:
        current_locations = current_locations[: args.location_limit]
        intent_locations = intent_locations[: args.location_limit]
    current_report, intent_report = await asyncio.gather(
        _run_variant(
            profile_key=profile_key,
            label=f"{profile_key}-current-live",
            terms=current_terms,
            locations=current_locations,
            args=args,
        ),
        _run_variant(
            profile_key=profile_key,
            label=f"{profile_key}-intent-planner",
            terms=intent_terms,
            locations=intent_locations,
            args=args,
        ),
    )
    current_job_urls = {
        str(job.get("job_url") or "")
        for approach in current_report.get("approaches") or []
        for job in approach.get("top_jobs") or []
    }
    intent_job_urls = {
        str(job.get("job_url") or "")
        for approach in intent_report.get("approaches") or []
        for job in approach.get("top_jobs") or []
    }
    result = {
        "profile": profile_key,
        "resume_chars": len(candidate_text),
        "current": {
            "terms": current_terms,
            "locations": current_locations,
            "query_count": len(current_report.get("queries") or []),
            "scraped_jobs": current_report.get("scraped_jobs"),
            "ranked_jobs": current_report.get("ranked_jobs"),
            "stage_timings_ms": current_report.get("stage_timings_ms"),
            "scrape_cache": current_report.get("scrape_cache"),
        },
        "intent": {
            "terms": intent_terms,
            "locations": intent_locations,
            "query_count": len(intent_report.get("queries") or []),
            "scraped_jobs": intent_report.get("scraped_jobs"),
            "ranked_jobs": intent_report.get("ranked_jobs"),
            "stage_timings_ms": intent_report.get("stage_timings_ms"),
            "scrape_cache": intent_report.get("scrape_cache"),
            "debug": build_query_plan_debug(
                intent_profile,
                max_terms=args.intent_term_limit,
            ),
        },
        "scraped_lift": int(intent_report.get("scraped_jobs") or 0)
        - int(current_report.get("scraped_jobs") or 0),
        "top_url_union": len((current_job_urls | intent_job_urls) - {""}),
        "comparisons": [
            _compare_reports(
                current_report,
                intent_report,
                approach_name=approach,
                top_k=args.analysis_k,
                min_non_reject_top=args.min_non_reject_top,
                max_reject_rate=args.max_reject_rate,
            )
            for approach in args.approach
        ],
    }
    result["passes"] = all(comparison["passes"] for comparison in result["comparisons"])
    return result


def _render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Live Scrape Query Planner Eval",
        "",
        f"- profiles: `{len(report['profiles'])}`",
        f"- passes: `{report['passes']}`",
        f"- days: `{report['days']}`",
        f"- current_term_limit: `{report['current_term_limit']}`",
        f"- intent_term_limit: `{report['intent_term_limit']}`",
        f"- max_results_per_query: `{report['max_results_per_query']}`",
        "",
        "| Profile | Passes | Current Terms | Intent Terms | Current Jobs | Intent Jobs | Lift | Non-Reject@K | Reject Rate | Top Overlap |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["profiles"]:
        first_comparison = item["comparisons"][0] if item["comparisons"] else {}
        lines.append(
            "| {profile} | {passes} | {current_terms} | {intent_terms} | {current_jobs} | {intent_jobs} | {lift} | {non_reject} | {reject_rate} | {overlap} |".format(
                profile=item["profile"],
                passes=item["passes"],
                current_terms=len(item["current"]["terms"]),
                intent_terms=len(item["intent"]["terms"]),
                current_jobs=item["current"]["scraped_jobs"],
                intent_jobs=item["intent"]["scraped_jobs"],
                lift=item["scraped_lift"],
                non_reject=first_comparison.get("intent_non_reject_top_count", 0),
                reject_rate=first_comparison.get("intent_reject_rate", 0),
                overlap=first_comparison.get("top_overlap_rate", 0),
            )
        )
    for item in report["profiles"]:
        lines.extend(["", f"## {item['profile']}", ""])
        lines.append(f"- current_locations: `{item['current']['locations']}`")
        lines.append(f"- intent_locations: `{item['intent']['locations']}`")
        lines.append(f"- current_terms: `{item['current']['terms']}`")
        lines.append(f"- intent_terms: `{item['intent']['terms']}`")
        lines.append(
            f"- intent_risk_flags: `{item['intent']['debug'].get('risk_flags') or []}`"
        )
        for comparison in item["comparisons"]:
            lines.append(
                "- {approach}: pass `{passes}`, non_reject `{non_reject}`, reject_rate `{reject_rate}`, overlap `{overlap}`, current bands `{current}`, intent bands `{intent}`".format(
                    approach=comparison["approach"],
                    passes=comparison["passes"],
                    non_reject=comparison["intent_non_reject_top_count"],
                    reject_rate=comparison["intent_reject_rate"],
                    overlap=comparison["top_overlap_rate"],
                    current=comparison["current_fit_counts"],
                    intent=comparison["intent_fit_counts"],
                )
            )
            if comparison["new_intent_top"]:
                lines.append("- new intent top:")
                for value in comparison["new_intent_top"][:5]:
                    lines.append(f"  - {value}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare live scrape/rank output for current vs intent query terms"
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(build_profile_eval_sets.PROFILE_FILES),
    )
    parser.add_argument("--location", action="append")
    parser.add_argument("--location-limit", type=int, default=3)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--current-term-limit", type=int, default=1)
    parser.add_argument("--intent-term-limit", type=int, default=8)
    parser.add_argument("--max-results-per-query", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--analysis-k", type=int, default=10)
    parser.add_argument("--min-non-reject-top", type=int, default=1)
    parser.add_argument("--max-reject-rate", type=float, default=0.8)
    parser.add_argument(
        "--approach",
        action="append",
        default=["deterministic_baseline"],
        choices=sorted(rank_resume_existing_corpus.APPROACHES),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


async def _async_main() -> None:
    args = _build_parser().parse_args()
    profiles = args.profile or list(DEFAULT_PROFILES)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-live-compare"
    run_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir = str(run_dir / "variants")
    report = {
        "profiles_requested": profiles,
        "days": args.days,
        "current_term_limit": args.current_term_limit,
        "intent_term_limit": args.intent_term_limit,
        "max_results_per_query": args.max_results_per_query,
        "min_non_reject_top": args.min_non_reject_top,
        "max_reject_rate": args.max_reject_rate,
        "profiles": [],
    }
    for profile in profiles:
        report["profiles"].append(await _run_profile(profile, args))
    report["passes"] = all(item["passes"] for item in report["profiles"])
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (run_dir / "summary.md").write_text(_render_summary(report) + "\n")
    print(json.dumps({"output_dir": str(run_dir), "profiles": profiles}, indent=2))


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
