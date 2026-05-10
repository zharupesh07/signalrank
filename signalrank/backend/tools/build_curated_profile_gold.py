from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from tools import build_profile_eval_sets
from tools import hybrid_match_eval as hybrid
from tools import rag_match_sample_eval as matcher

DEFAULT_REPORT_ROOT = (
    Path(__file__).resolve().parents[1] / "tmp" / "resume_existing_corpus_rank"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "evals"

DEFAULT_LABEL_LIMITS = {
    "strong_pursue": 10,
    "maybe_adjacent": 8,
    "reject": 10,
    "hard_violation": 8,
}
GENERIC_SCRAPE_TERMS = {
    "api",
    "aws",
    "azure",
    "cloud",
    "developer",
    "engineer",
    "gcp",
    "java",
    "linux",
    "python",
    "software engineer",
}
WEAK_CONTEXT_ONLY_TERMS = {
    "emerging",
    "innovation",
    "mvp",
    "poc",
    "prototype",
    "prototyping",
    "research",
}
SENIORITY_HARD_NEGATIVE_TERMS = {
    "associate",
    "cto",
    "director",
    "entry-level",
    "entry level",
    "head",
    "intern",
    "junior",
    "manager",
    "principal",
    "vp",
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _has(text: str, *terms: str) -> bool:
    return any(hybrid._has_phrase(text, term) for term in terms)


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _clean_description(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _profile_report_tokens(profile: str) -> tuple[str, ...]:
    resume_file = build_profile_eval_sets.PROFILE_FILES.get(profile, profile)
    resume_stem = Path(resume_file).stem
    return tuple(
        {
            _norm(profile).replace(" ", "-"),
            _norm(profile).replace(" ", "_"),
            _norm(resume_stem).replace(" ", "-"),
            _norm(resume_stem).replace(" ", "_"),
        }
    )


def _load_signalrank_jobs(profile: str, report_root: Path) -> list[dict[str, Any]]:
    jobs_by_url: dict[str, dict[str, Any]] = {}
    tokens = _profile_report_tokens(profile)
    paths = [
        path
        for path in sorted(report_root.glob("*/jobspy_scrape_report.json"))
        if any(token and token in _norm(str(path)) for token in tokens)
    ]
    for path in paths:
        report = json.loads(path.read_text())
        for approach in report.get("approaches") or []:
            for job in approach.get("top_jobs") or []:
                url = str(job.get("job_url") or "").strip()
                if not url:
                    continue
                score = float(job.get("final_score") or 0.0)
                rank = int(job.get("rank") or 9999)
                current = jobs_by_url.get(url)
                if current and (
                    current["source_rank"],
                    -current["source_score"],
                ) <= (rank, -score):
                    continue
                jobs_by_url[url] = {
                    "company": str(job.get("company") or ""),
                    "description": _clean_description(job.get("description") or ""),
                    "job_url": url,
                    "location": str(job.get("location") or "") or None,
                    "source": "signalrank_resume_existing_corpus",
                    "source_band": job.get("fit_band"),
                    "source_report": str(path),
                    "source_score": round(score, 4),
                    "source_rank": rank,
                    "title": str(job.get("title") or ""),
                }
    return sorted(
        jobs_by_url.values(),
        key=lambda item: (item["source_rank"], -item["source_score"], item["title"]),
    )


def _policy_filter_terms(policy: hybrid.MatchPolicy) -> tuple[str, ...]:
    terms = [
        *policy.direct_title_terms,
        *policy.direct_context_terms,
        *policy.adjacent_title_terms,
    ]
    return tuple(
        term
        for term in build_profile_eval_sets._dedupe(terms, limit=40)
        if term not in GENERIC_SCRAPE_TERMS and len(term) >= 3
    )


def _load_career_ops_jobs(
    policy: hybrid.MatchPolicy, career_ops_root: Path
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    output_dir = career_ops_root / "output"
    if not output_dir.exists():
        return jobs
    profile_terms = _policy_filter_terms(policy)
    for path in sorted(output_dir.glob("*.tsv")):
        lines = path.read_text(errors="ignore").splitlines()
        if not lines:
            continue
        header = lines[0].split("\t")
        for line in lines[1:]:
            values = line.split("\t")
            row = dict(zip(header, values, strict=False))
            title = str(row.get("title") or "")
            combined = _norm(
                " ".join(
                    [
                        title,
                        str(row.get("company") or ""),
                        str(row.get("matched_terms") or ""),
                    ]
                )
            )
            if not _contains(combined, *profile_terms):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            jobs.append(
                {
                    "company": str(row.get("company") or ""),
                    "description": "",
                    "job_url": url,
                    "location": None,
                    "source": "career_ops_output",
                    "source_band": None,
                    "source_report": str(path),
                    "source_score": float(row.get("score") or 0.0),
                    "source_rank": 999,
                    "title": title,
                }
            )
    return jobs


def _eval_job(
    job: dict[str, Any],
    *,
    profile: dict[str, Any],
    resume_text: str,
    policy: hybrid.MatchPolicy,
    chunks: list[matcher.EvidenceChunk],
) -> tuple[hybrid.SimpleScore, matcher.MatchFactors]:
    current_score = float(job.get("source_score") or 0.0)
    eval_job = hybrid.EvalJob(
        label="unlabeled",
        label_reason="pending",
        current_score=current_score,
        current_fit_band=job.get("source_band"),
        title=str(job.get("title") or ""),
        company=str(job.get("company") or ""),
        location=job.get("location"),
        job_url=str(job.get("job_url") or ""),
        description=str(job.get("description") or ""),
    )
    sample = matcher.SampleJob(
        expected="unlabeled",
        current_score=current_score,
        current_fit_band=eval_job.current_fit_band,
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
    return (
        hybrid._simplified_score(
            factors,
            job=eval_job,
            current_score=current_score,
            match_policy=policy,
        ),
        factors,
    )


def _has_meaningful_direct_context(text: str, policy: hybrid.MatchPolicy) -> bool:
    hits = [
        term
        for term in policy.direct_context_terms
        if term not in WEAK_CONTEXT_ONLY_TERMS and hybrid._has_phrase(text, term)
    ]
    return bool(hits)


def _is_network_automation_policy(policy: hybrid.MatchPolicy) -> bool:
    return "network_automation" in policy.active_lanes


def _is_sap_policy(policy: hybrid.MatchPolicy) -> bool:
    return "sap_erp" in policy.active_lanes


def _is_emerging_tech_policy(policy: hybrid.MatchPolicy) -> bool:
    return any(
        lane in policy.active_lanes
        for lane in ("innovation", "iot", "conversational_ai")
    )


def _has_network_automation_evidence(text: str) -> bool:
    return hybrid._has_network_automation_evidence(text)


def _has_sap_evidence(text: str) -> bool:
    return hybrid._has_sap_evidence(text)


def _has_emerging_solution_evidence(text: str) -> bool:
    return any(
        hybrid._has_phrase(text, term)
        for term in hybrid.EMERGING_TECH_SOLUTION_EVIDENCE
    )


def _has_specific_emerging_title(title: str) -> bool:
    return any(
        hybrid._has_phrase(title, term) for term in hybrid.SPECIFIC_EMERGING_TITLES
    )


def _has_generic_emerging_title(title: str) -> bool:
    return any(
        hybrid._has_phrase(title, term) for term in hybrid.GENERIC_EMERGING_TITLES
    )


def _label_job(
    job: dict[str, Any],
    *,
    score: hybrid.SimpleScore,
    factors: matcher.MatchFactors,
    policy: hybrid.MatchPolicy,
) -> tuple[str, str]:
    title = _norm(job["title"])
    context = _norm(f"{job['title']} {job.get('description') or ''}")
    direct_title_hit = any(
        hybrid._has_phrase(title, term) for term in policy.direct_title_terms
    )
    direct_context_in_title = any(
        hybrid._has_phrase(title, term)
        for term in policy.direct_context_terms
        if term not in WEAK_CONTEXT_ONLY_TERMS
    )
    meaningful_context = _has_meaningful_direct_context(context, policy)
    adjacent_title_hit = any(
        hybrid._has_phrase(title, term) for term in policy.adjacent_title_terms
    )
    explicit_domain_title = _has(
        title,
        "ai",
        "ml",
        "genai",
        "agentic",
        "conversational",
        "computer vision",
        "iot",
        "embedded",
        "robotics",
        "r&d",
        "prototype",
        "creative technologist",
    )
    title_seniority_hard_negative = any(
        hybrid._has_phrase(title, term) for term in SENIORITY_HARD_NEGATIVE_TERMS
    ) or bool(re.search(r"(^|[-_\s])sm($|[-_\s])", title))

    if "sap_erp" not in policy.active_lanes and hybrid._has_phrase(title, "sap"):
        return "hard_violation", "non_target_sap_lane"
    if "qa_automation" not in policy.active_lanes and _has(
        title,
        "qa",
        "quality engineer",
        "test engineer",
        "testing",
        "software development engineer in test",
        "sdet",
    ):
        return "hard_violation", "non_target_qa_or_test_lane"
    if title_seniority_hard_negative:
        return "hard_violation", "seniority_or_manager_title_lane"
    if "hard_negative_title_lane" in score.gate_reasons:
        return "hard_violation", "hard_negative_title_lane"
    if "non_target_engineering_lane" in score.gate_reasons:
        return "hard_violation", "non_target_engineering_lane"
    if any(
        reason
        in {
            "data_pipeline_without_ai_platform_context",
            "junior_or_entry_data_lane",
        }
        for reason in score.gate_reasons
    ):
        return "reject", ",".join(score.gate_reasons)
    if _is_sap_policy(policy):
        if any(reason.startswith("sap_") for reason in score.gate_reasons):
            return "reject", ",".join(score.gate_reasons)
        if direct_title_hit:
            return "strong_pursue", "sap_direct_title_match"
        if _has_sap_evidence(context) and (
            direct_context_in_title or meaningful_context
        ):
            return "strong_pursue", "sap_context_with_module_evidence"
        if adjacent_title_hit or score.score >= 55:
            return "maybe_adjacent", "partial_sap_policy_match"
        return "reject", "weak_or_generic_sap_match"
    if _is_network_automation_policy(policy):
        if direct_title_hit or direct_context_in_title:
            if _has_network_automation_evidence(context):
                return "strong_pursue", "network_role_with_automation_evidence"
            return "maybe_adjacent", "network_role_without_automation_evidence"
        if adjacent_title_hit or score.score >= 55:
            return "maybe_adjacent", "partial_network_policy_match"
        return "reject", "weak_or_generic_network_match"
    if _is_emerging_tech_policy(policy):
        specific_title = _has_specific_emerging_title(title)
        solution_evidence = _has_emerging_solution_evidence(context)
        generic_title = _has_generic_emerging_title(title)
        if specific_title and (meaningful_context or solution_evidence):
            return "strong_pursue", "specific_emerging_tech_title_and_context"
        if solution_evidence and explicit_domain_title and not generic_title:
            return "strong_pursue", "emerging_solution_context_with_domain_title"
        if (
            direct_title_hit
            or adjacent_title_hit
            or explicit_domain_title
            or score.score >= 55
        ):
            return "maybe_adjacent", "partial_emerging_tech_policy_match"
        return "reject", "weak_or_generic_emerging_tech_match"
    if direct_title_hit and (meaningful_context or direct_context_in_title):
        return "strong_pursue", "direct_title_and_profile_context_match"
    if direct_context_in_title:
        return "strong_pursue", "profile_context_in_title_with_evidence"
    if meaningful_context and explicit_domain_title:
        return "strong_pursue", "profile_context_with_specific_solution_title"
    if direct_title_hit or adjacent_title_hit or score.score >= 55:
        return "maybe_adjacent", "partial_profile_policy_match"
    return "reject", "weak_or_generic_profile_match"


def _dedupe_by_title_company(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (_norm(row["title"]), _norm(row["company"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _select_balanced(
    jobs: list[dict[str, Any]],
    label_limits: dict[str, int],
) -> list[dict[str, Any]]:
    labeled: dict[str, list[dict[str, Any]]] = {
        "strong_pursue": [],
        "maybe_adjacent": [],
        "reject": [],
        "hard_violation": [],
    }
    for job in jobs:
        labeled[str(job["label"])].append(job)

    selected: list[dict[str, Any]] = []
    for label, limit in label_limits.items():
        selected.extend(_dedupe_by_title_company(labeled[label])[:limit])
    return sorted(
        selected,
        key=lambda item: (
            hybrid.LABEL_ORDER[item["label"]],
            item["source_rank"],
            -item["source_score"],
            item["title"],
        ),
        reverse=True,
    )


def build_gold_set(
    profile: str,
    *,
    report_root: Path,
    career_ops_root: Path,
    output_dir: Path,
    label_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    candidate_profile, resume_text = build_profile_eval_sets.build_profile(profile)
    policy = hybrid._build_match_policy(candidate_profile)
    chunks = matcher._resume_chunks(resume_text, candidate_profile)
    signalrank_jobs = _load_signalrank_jobs(profile, report_root)
    career_ops_jobs = _load_career_ops_jobs(policy, career_ops_root)
    by_url = {job["job_url"]: job for job in signalrank_jobs}
    for job in career_ops_jobs:
        by_url.setdefault(job["job_url"], job)
    labeled_jobs = []
    for job in by_url.values():
        if not job.get("description") and job["source"] != "career_ops_output":
            continue
        score, factors = _eval_job(
            job,
            profile=candidate_profile,
            resume_text=resume_text,
            policy=policy,
            chunks=chunks,
        )
        label, reason = _label_job(job, score=score, factors=factors, policy=policy)
        labeled_jobs.append(
            {
                **job,
                "label": label,
                "label_reason": reason,
                "review_status": "gold_curated",
            }
        )
    rows = _select_balanced(labeled_jobs, label_limits or DEFAULT_LABEL_LIMITS)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{profile}_job_fit_gold.jsonl"
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = Counter(row["label"] for row in rows)
    return {
        "career_ops_candidates": len(career_ops_jobs),
        "label_counts": dict(sorted(counts.items())),
        "path": str(path),
        "profile": profile,
        "rows": len(rows),
        "scrape_terms": build_scrape_terms(candidate_profile, policy),
        "signalrank_candidates": len(signalrank_jobs),
    }


def build_scrape_terms(
    candidate_profile: dict[str, Any],
    policy: hybrid.MatchPolicy,
    *,
    limit: int = 12,
) -> list[str]:
    role_terms = [
        *candidate_profile.get("target_roles_primary", []),
        *policy.direct_title_terms,
        *policy.adjacent_title_terms,
    ]
    context_terms = [
        term
        for term in policy.direct_context_terms
        if term not in GENERIC_SCRAPE_TERMS and len(term) >= 3
    ]
    terms: list[str] = []
    for term in role_terms:
        clean = str(term).split("|")[0].strip()
        if clean and len(clean) <= 60:
            terms.append(clean)
    for role in role_terms[:6]:
        role_clean = str(role).split("|")[0].strip()
        if not role_clean or len(role_clean) > 45:
            continue
        for context in context_terms[:4]:
            if context not in _norm(role_clean):
                terms.append(f"{role_clean} {context}")
    return build_profile_eval_sets._dedupe(terms, limit=limit)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build curated profile gold JSONL")
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(build_profile_eval_sets.PROFILE_FILES),
    )
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument(
        "--career-ops-root",
        default=str(Path(__file__).resolve().parents[3] / "career-ops"),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    profiles = args.profile or sorted(build_profile_eval_sets.PROFILE_FILES)
    results = [
        build_gold_set(
            profile,
            report_root=Path(args.report_root).expanduser().resolve(),
            career_ops_root=Path(args.career_ops_root).expanduser().resolve(),
            output_dir=Path(args.output_dir).expanduser().resolve(),
        )
        for profile in profiles
    ]
    print(json.dumps({"profiles": results}, indent=2))


if __name__ == "__main__":
    main()
