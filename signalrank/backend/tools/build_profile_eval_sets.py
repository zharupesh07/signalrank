from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from api.database import AsyncSessionLocal, engine
from api.models import JobRaw
from api.routes.onboarding import _extract_text_from_pdf
from domain.candidate_profile import build_candidate_profile
from llm.resume_parser import ResumeParseResult
from tools import hybrid_match_eval as hybrid
from tools import rag_match_sample_eval as matcher

RESUMES_DIR = Path(__file__).resolve().parents[3] / "resumes"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "evals"
DEFAULT_PROFILES = ("abhijeet", "aditya", "ayush", "vivek")
PROFILE_FILES = {
    "abhijeet": "Abhijeet_CV.pdf",
    "aditya": "aditya.pdf",
    "ayush": "ayush_resume_new.pdf",
    "vivek": "Vivek-Gupta-Emerging-Technologies.pdf",
    "example": "Example_Candidate_Resume_V2_2.pdf",
}


def _dedupe(values: list[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _load_spec(profile_key: str) -> dict[str, Any]:
    return json.loads(
        (RESUMES_DIR / PROFILE_FILES[profile_key]).with_suffix(".json").read_text()
    )


def _resume_text(profile_key: str, spec: dict[str, Any]) -> str:
    pdf_path = RESUMES_DIR / PROFILE_FILES[profile_key]
    if pdf_path.exists():
        return _extract_text_from_pdf(pdf_path.read_bytes())
    parts = [
        str(spec.get("name") or ""),
        str(spec.get("position") or spec.get("label") or ""),
        str(spec.get("summary") or ""),
    ]
    for exp in spec.get("experiences") or []:
        if isinstance(exp, dict):
            parts.append(str(exp.get("title") or ""))
            parts.extend(str(item) for item in exp.get("bullets") or [])
    for group in spec.get("skills") or []:
        if isinstance(group, dict):
            parts.extend(str(item) for item in group.get("items") or [])
    return "\n".join(part for part in parts if part)


def _parse_spec(spec: dict[str, Any]) -> ResumeParseResult:
    skills: list[str] = []
    for group in spec.get("skills") or []:
        if isinstance(group, dict):
            skills.extend(str(item) for item in group.get("items") or [])
    recent_titles = [
        str(exp.get("title") or "")
        for exp in spec.get("experiences") or []
        if isinstance(exp, dict) and str(exp.get("title") or "").strip()
    ][:3]
    education = [
        str(edu.get("degree") or "")
        for edu in spec.get("education") or []
        if isinstance(edu, dict) and str(edu.get("degree") or "").strip()
    ]
    location = str(spec.get("location") or "").strip()
    location_city = location.split(",")[0].strip() if location else ""
    headline = str(spec.get("position") or spec.get("label") or "").strip()
    suggested_roles = [headline] if headline else recent_titles[:1]
    return ResumeParseResult(
        skills=skills,
        years_of_experience=None,
        recent_titles=recent_titles,
        industries=[],
        education=education,
        suggested_roles=suggested_roles,
        suggested_locations=[location_city] if location_city else [],
        suggested_exclusions=[],
        suggested_search_queries=[],
        career_archetypes=[],
        ambiguities=[],
    )


def build_profile(profile_key: str) -> tuple[dict[str, Any], str]:
    spec = _load_spec(profile_key)
    resume_text = _resume_text(profile_key, spec)
    parsed = _parse_spec(spec)
    profile = build_candidate_profile(parsed=parsed, resume_text=resume_text)
    return profile, resume_text


def _title_has_any(title: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(hybrid._has_phrase(title, term) for term in terms)


def _positive_policy_title_terms(policy: hybrid.MatchPolicy) -> tuple[str, ...]:
    generic_terms = {
        "python",
        "sql",
        "aws",
        "gcp",
        "java",
        "c++",
        "shell",
        "shell scripting",
        "ms office",
    }
    return tuple(
        term
        for term in policy.direct_context_terms
        if term not in generic_terms and len(term) >= 4
    )


def _label_from_score(
    score: hybrid.SimpleScore,
    *,
    title: str,
    policy: hybrid.MatchPolicy,
) -> tuple[str, str]:
    if "hard_negative_title_lane" in score.gate_reasons:
        return "hard_violation", "hard_negative_title_lane"
    hard_policy_gate = any(
        reason
        in {
            "non_target_engineering_lane",
            "data_pipeline_without_ai_platform_context",
            "junior_or_entry_data_lane",
        }
        for reason in score.gate_reasons
    )
    if hard_policy_gate:
        return "reject", ",".join(score.gate_reasons) or "score_below_fit_threshold"
    if _title_has_any(title, policy.direct_title_terms):
        return "strong_pursue", "profile_policy_direct_title_match"
    if _title_has_any(title, _positive_policy_title_terms(policy)):
        return "strong_pursue", "profile_policy_domain_title_match"
    if score.gate_failed:
        return "reject", ",".join(score.gate_reasons) or "score_below_fit_threshold"
    if score.score < 35:
        return "reject", "score_below_fit_threshold"
    if score.score >= 75:
        return "strong_pursue", "profile_policy_direct_or_high_evidence_match"
    if score.score >= 55:
        return "maybe_adjacent", "profile_policy_adjacent_or_partial_match"
    if _title_has_any(title, policy.adjacent_title_terms):
        return "maybe_adjacent", "profile_policy_adjacent_title_match"
    return "reject", "weak_profile_policy_match"


def _confidence(label: str, score: hybrid.SimpleScore) -> str:
    if label in {"hard_violation", "reject"} and score.gate_failed:
        return "high"
    if label == "strong_pursue" and score.score >= 90:
        return "high"
    if label == "maybe_adjacent":
        return "medium"
    return "low"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "profile"


async def _fetch_jobs(min_description_chars: int, max_jobs: int) -> list[JobRaw]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobRaw)
                .where(func.length(JobRaw.description) >= min_description_chars)
                .order_by(JobRaw.title, JobRaw.company)
                .limit(max_jobs)
            )
        ).scalars()
        return list(rows)


async def _fetch_policy_jobs(
    policy: hybrid.MatchPolicy,
    *,
    min_description_chars: int,
    max_jobs: int,
) -> list[JobRaw]:
    terms = _dedupe(
        [
            *policy.direct_title_terms,
            *policy.direct_context_terms,
            *policy.adjacent_title_terms,
        ],
        limit=24,
    )
    if not terms:
        return []
    per_term_limit = max(15, max_jobs // max(1, len(terms)))
    jobs_by_url: dict[str, JobRaw] = {}
    async with AsyncSessionLocal() as db:
        for term in terms:
            pattern = f"%{term}%"
            title_rows = (
                await db.execute(
                    select(JobRaw)
                    .where(
                        func.length(JobRaw.description) >= min_description_chars,
                        JobRaw.title.ilike(pattern),
                    )
                    .order_by(JobRaw.title, JobRaw.company)
                    .limit(per_term_limit)
                )
            ).scalars()
            for row in title_rows:
                jobs_by_url.setdefault(str(row.job_url or ""), row)
            if len(jobs_by_url) >= max_jobs:
                break
        if len(jobs_by_url) < max_jobs:
            for term in terms:
                pattern = f"%{term}%"
                description_rows = (
                    await db.execute(
                        select(JobRaw)
                        .where(
                            func.length(JobRaw.description) >= min_description_chars,
                            JobRaw.description.ilike(pattern),
                        )
                        .order_by(JobRaw.title, JobRaw.company)
                        .limit(per_term_limit)
                    )
                ).scalars()
                for row in description_rows:
                    jobs_by_url.setdefault(str(row.job_url or ""), row)
                    if len(jobs_by_url) >= max_jobs:
                        break
                if len(jobs_by_url) >= max_jobs:
                    break
    return list(jobs_by_url.values())


def _score_job(
    *,
    job: JobRaw,
    profile: dict[str, Any],
    resume_text: str,
    chunks: list[matcher.EvidenceChunk],
    policy: hybrid.MatchPolicy,
) -> dict[str, Any]:
    eval_job = hybrid.EvalJob(
        label="unlabeled",
        label_reason="pending",
        current_score=0.0,
        current_fit_band=None,
        title=str(job.title or ""),
        company=str(job.company or ""),
        location=str(job.location or "") or None,
        job_url=str(job.job_url or ""),
        description=str(job.description or ""),
    )
    sample = matcher.SampleJob(
        expected="unlabeled",
        current_score=0.0,
        current_fit_band=None,
        title=eval_job.title,
        company=eval_job.company,
        location=eval_job.location,
        job_url=eval_job.job_url,
        description=eval_job.description,
    )
    requirements = matcher.extract_requirements(sample)
    requirement_results = matcher.evaluate_requirements(requirements, chunks)
    factors = matcher.synthesize_hybrid_score(
        requirements,
        requirement_results,
        chunks,
        resume_text,
        profile,
        sample,
    )
    simple = hybrid._simplified_score(
        factors,
        job=eval_job,
        current_score=0.0,
        match_policy=policy,
    )
    label, reason = _label_from_score(
        simple,
        title=eval_job.title,
        policy=policy,
    )
    return {
        "job_url": eval_job.job_url,
        "label": label,
        "label_reason": reason,
        "title": eval_job.title,
        "company": eval_job.company,
        "location": eval_job.location,
        "confidence": _confidence(label, simple),
        "simplified_score": simple.score,
        "simplified_band": simple.band,
        "gate_reasons": simple.gate_reasons,
        "hybrid_score": factors.final_score,
        "role_score": factors.role_score,
        "evidence_score": factors.evidence_score,
        "skill_score": factors.skill_score,
    }


def _balanced_rows(
    rows: list[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    buckets = {
        "strong_pursue": [],
        "maybe_adjacent": [],
        "reject": [],
        "hard_violation": [],
    }
    for row in sorted(rows, key=lambda item: item["simplified_score"], reverse=True):
        buckets[row["label"]].append(row)
    target_counts = {
        "strong_pursue": sample_size // 4,
        "maybe_adjacent": sample_size // 4,
        "reject": sample_size // 3,
        "hard_violation": max(
            5, sample_size - (sample_size // 4) * 2 - sample_size // 3
        ),
    }
    selected: list[dict[str, Any]] = []
    for label, count in target_counts.items():
        selected.extend(buckets[label][:count])
    if len(selected) < sample_size:
        seen = {row["job_url"] for row in selected}
        for row in rows:
            if row["job_url"] in seen:
                continue
            selected.append(row)
            seen.add(row["job_url"])
            if len(selected) >= sample_size:
                break
    return selected[:sample_size]


def _public_row(row: dict[str, Any], *, gold_seed: bool) -> dict[str, Any]:
    keys = [
        "job_url",
        "label",
        "label_reason",
        "title",
        "company",
        "location",
        "confidence",
    ]
    item = {key: row[key] for key in keys if row.get(key) is not None}
    if gold_seed:
        item["review_status"] = "seed_review_needed"
    return item


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")


async def build_eval_sets(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_jobs = await _fetch_jobs(args.min_description_chars, args.max_jobs)
    summary: dict[str, Any] = {"profiles": {}, "output_dir": str(output_dir)}
    for profile_key in args.profile:
        profile, resume_text = build_profile(profile_key)
        policy = hybrid._build_match_policy(profile)
        policy_jobs = await _fetch_policy_jobs(
            policy,
            min_description_chars=args.min_description_chars,
            max_jobs=args.max_jobs,
        )
        jobs_by_url: dict[str, JobRaw] = {}
        for job in [*policy_jobs, *base_jobs]:
            jobs_by_url.setdefault(str(job.job_url or ""), job)
        jobs = list(jobs_by_url.values())
        chunks = matcher._resume_chunks(resume_text, profile)
        scored = [
            _score_job(
                job=job,
                profile=profile,
                resume_text=resume_text,
                chunks=chunks,
                policy=policy,
            )
            for job in jobs
        ]
        scored.sort(key=lambda item: item["simplified_score"], reverse=True)
        selected = _balanced_rows(scored, args.sample_size)
        silver_rows = [_public_row(row, gold_seed=False) for row in selected]
        gold_seed_rows = [_public_row(row, gold_seed=True) for row in selected]
        silver_path = output_dir / f"{profile_key}_job_fit_silver.jsonl"
        gold_seed_path = output_dir / f"{profile_key}_job_fit_gold_seed.jsonl"
        _write_jsonl(silver_path, silver_rows)
        _write_jsonl(gold_seed_path, gold_seed_rows)
        summary["profiles"][profile_key] = {
            "silver_path": str(silver_path),
            "gold_seed_path": str(gold_seed_path),
            "active_lanes": policy.active_lanes,
            "target_roles_primary": _dedupe(
                [str(item) for item in profile.get("target_roles_primary") or []],
                limit=6,
            ),
            "label_counts": {
                label: sum(1 for row in selected if row["label"] == label)
                for label in (
                    "strong_pursue",
                    "maybe_adjacent",
                    "reject",
                    "hard_violation",
                )
            },
        }
    (output_dir / "profile_eval_sets_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build profile-specific silver and seed-gold job-fit eval JSONL files."
    )
    parser.add_argument(
        "--profile", action="append", choices=sorted(PROFILE_FILES), default=[]
    )
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--max-jobs", type=int, default=4000)
    parser.add_argument("--min-description-chars", type=int, default=500)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


async def _async_main() -> None:
    args = _parser().parse_args()
    if not args.profile:
        args.profile = list(DEFAULT_PROFILES)
    summary = await build_eval_sets(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    await engine.dispose()


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
