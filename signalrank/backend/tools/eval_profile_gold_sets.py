from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import build_profile_eval_sets
from tools import hybrid_match_eval as hybrid
from tools import rag_match_sample_eval as matcher
from domain.intent_matching import (
    PROFILE_INTENT_KEY,
    build_job_intent,
    build_profile_intent,
    score_intent_match,
)

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "profile_gold_eval"
DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "evals"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _eval_row(
    row: dict[str, Any],
    *,
    resume_text: str,
    candidate_profile: dict[str, Any],
    match_policy: hybrid.MatchPolicy,
    profile_intent: dict[str, Any],
    chunks: list[matcher.EvidenceChunk],
) -> dict[str, Any]:
    current_score = float(row.get("source_score") or row.get("current_score") or 0.0)
    eval_job = hybrid.EvalJob(
        label=str(row["label"]),
        label_reason=str(row.get("label_reason") or "gold"),
        current_score=current_score,
        current_fit_band=row.get("source_band"),
        title=str(row.get("title") or ""),
        company=str(row.get("company") or ""),
        location=row.get("location"),
        job_url=str(row.get("job_url") or ""),
        description=str(row.get("description") or ""),
    )
    sample = matcher.SampleJob(
        expected=eval_job.label,
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
        candidate_profile,
        sample,
    )
    simplified = hybrid._simplified_score(
        factors,
        job=eval_job,
        current_score=current_score,
        match_policy=match_policy,
    )
    job_intent = build_job_intent(
        title=eval_job.title,
        company=eval_job.company,
        description=eval_job.description,
        location=eval_job.location,
    )
    intent_decision = score_intent_match(
        profile_intent,
        job_intent,
        current_score=current_score,
    )
    return {
        **asdict(eval_job),
        "current_band": hybrid._current_band(current_score),
        "description": "",
        "factors": {
            key: value
            for key, value in asdict(factors).items()
            if key not in {"band", "hard_constraints"}
        },
        "hard_constraints": factors.hard_constraints,
        "hybrid_band": factors.band,
        "hybrid_score": factors.final_score,
        "simple_gate_failed": simplified.gate_failed,
        "simple_gate_reasons": simplified.gate_reasons,
        "simplified_band": simplified.band,
        "simplified_score": simplified.score,
        "intent_band": intent_decision["band"],
        "intent_score": intent_decision["score"],
        "intent_decision": intent_decision,
        "job_intent": job_intent,
        "source": row.get("source"),
        "source_rank": row.get("source_rank"),
        "source_report": row.get("source_report"),
        "source_score": row.get("source_score"),
    }


def run_eval(profile: str, labels_path: Path, top_k: int) -> dict[str, Any]:
    candidate_profile, resume_text = build_profile_eval_sets.build_profile(profile)
    match_policy = hybrid._build_match_policy(candidate_profile)
    profile_intent = candidate_profile.get(PROFILE_INTENT_KEY)
    if not isinstance(profile_intent, dict):
        profile_intent = build_profile_intent(
            candidate_profile, resume_text=resume_text
        )
    chunks = matcher._resume_chunks(resume_text, candidate_profile)
    rows = [
        _eval_row(
            row,
            resume_text=resume_text,
            candidate_profile=candidate_profile,
            match_policy=match_policy,
            profile_intent=profile_intent,
            chunks=chunks,
        )
        for row in _load_rows(labels_path)
    ]
    metric_k = min(top_k, len(rows))
    metrics = {
        "current": hybrid._score_metrics(
            rows,
            score_key="current_score",
            band_key="current_band",
            top_k=metric_k,
        ),
        "hybrid": hybrid._score_metrics(
            rows,
            score_key="hybrid_score",
            band_key="hybrid_band",
            top_k=metric_k,
        ),
        "simplified": hybrid._score_metrics(
            rows,
            score_key="simplified_score",
            band_key="simplified_band",
            top_k=metric_k,
        ),
        "intent": hybrid._score_metrics(
            rows,
            score_key="intent_score",
            band_key="intent_band",
            top_k=metric_k,
        ),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labels_path": str(labels_path),
        "match_policy": asdict(match_policy),
        "metrics": metrics,
        "gates": _eval_gates(rows, metrics, top_k=metric_k),
        "profile_intent": profile_intent,
        "profile": profile,
        "rows": rows,
    }


def _eval_gates(
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    *,
    top_k: int,
) -> dict[str, Any]:
    intent_metrics = metrics["intent"]
    ranked = sorted(rows, key=lambda item: item["intent_score"], reverse=True)
    top = ranked[:top_k]
    promoted_bad = [
        {
            "label": row["label"],
            "score": row["intent_score"],
            "band": row["intent_band"],
            "title": row["title"],
            "company": row["company"],
        }
        for row in ranked
        if row["label"] in {"reject", "hard_violation"}
        and row["intent_band"] in {"strong_fit", "adjacent_fit"}
    ]
    strong_without_evidence = []
    for row in ranked:
        if row["intent_band"] != "strong_fit":
            continue
        reasons_up = row.get("intent_decision", {}).get("reasons_up") or []
        has_evidence = any(
            str(reason).startswith(("skill_overlap", "domain_overlap"))
            or reason == "target_title_evidence"
            for reason in reasons_up
        )
        if not has_evidence:
            strong_without_evidence.append(
                {
                    "label": row["label"],
                    "score": row["intent_score"],
                    "title": row["title"],
                    "company": row["company"],
                    "reasons_up": reasons_up,
                }
            )
    checks = {
        "no_hard_violation_at_k": intent_metrics["hard_violation_at_k"] == 0,
        "no_rejects_promoted_at_k": intent_metrics["rejects_promoted_at_k"] == 0,
        "no_promoted_bad_anywhere": not promoted_bad,
        "strong_fit_has_evidence": not strong_without_evidence,
    }
    return {
        "top_k": top_k,
        "passes": all(checks.values()),
        "checks": checks,
        "top_labels": [row["label"] for row in top],
        "promoted_bad": promoted_bad[:20],
        "strong_without_evidence": strong_without_evidence[:20],
    }


def _render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Profile Gold Eval",
        "",
        f"- profile: `{report['profile']}`",
        f"- labels_path: `{report['labels_path']}`",
        f"- rows: `{len(report['rows'])}`",
        "",
        "| Approach | Precision@K | Hard violation@K | Rejects promoted@K | Pairwise | NDCG@10 | NDCG@25 | NDCG@50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in report["metrics"].items():
        lines.append(
            "| {name} | {precision_at_k:.3f} | {hard_violation_at_k:.3f} | {rejects_promoted_at_k:.3f} | {pairwise} | {ndcg10:.3f} | {ndcg25:.3f} | {ndcg50:.3f} |".format(
                name=name,
                precision_at_k=metrics["precision_at_k"],
                hard_violation_at_k=metrics["hard_violation_at_k"],
                rejects_promoted_at_k=metrics["rejects_promoted_at_k"],
                pairwise=metrics["pairwise_preference_accuracy"],
                ndcg10=metrics["ndcg_at_10"],
                ndcg25=metrics["ndcg_at_25"],
                ndcg50=metrics["ndcg_at_50"],
            )
        )
    gates = report.get("gates") or {}
    if gates:
        lines.extend(["", "## Intent Gates", ""])
        lines.append(f"- passes: `{gates['passes']}`")
        for name, passed in gates.get("checks", {}).items():
            lines.append(f"- {name}: `{passed}`")
        if gates.get("promoted_bad"):
            lines.extend(["", "### Intent Promoted Bad", ""])
            for item in gates["promoted_bad"]:
                lines.append(
                    "- {label} | {score:.1f} | {band} | {title} / {company}".format(
                        **item
                    )
                )
        if gates.get("strong_without_evidence"):
            lines.extend(["", "### Intent Strong Without Evidence", ""])
            for item in gates["strong_without_evidence"]:
                lines.append(
                    "- {label} | {score:.1f} | {title} / {company} | {reasons_up}".format(
                        **item
                    )
                )
    lines.extend(["", "## Simplified Top Jobs", ""])
    for item in report["metrics"]["simplified"]["top_jobs"]:
        lines.append(
            "- {label} | {score:.1f} | {band} | {title} / {company}".format(**item)
        )
    promoted = report["metrics"]["simplified"]["promoted_bad"]
    if promoted:
        lines.extend(["", "## Promoted Bad", ""])
        for item in promoted:
            lines.append(
                "- {label} | {score:.1f} | {band} | {title} / {company}".format(**item)
            )
    lines.extend(["", "## Intent Diff", ""])
    simplified_order = {
        item["job_url"]: index
        for index, item in enumerate(
            sorted(
                report["rows"], key=lambda row: row["simplified_score"], reverse=True
            )
        )
    }
    intent_order = {
        item["job_url"]: index
        for index, item in enumerate(
            sorted(report["rows"], key=lambda row: row["intent_score"], reverse=True)
        )
    }
    changed = sorted(
        report["rows"],
        key=lambda row: intent_order[row["job_url"]] - simplified_order[row["job_url"]],
    )
    for item in changed[:5]:
        delta = simplified_order[item["job_url"]] - intent_order[item["job_url"]]
        if delta <= 0:
            continue
        lines.append(
            "- up {delta}: {label} | intent {intent_score:.1f} | simple {simplified_score:.1f} | {title} / {company}".format(
                delta=delta,
                **item,
            )
        )
    for item in reversed(changed[-5:]):
        delta = simplified_order[item["job_url"]] - intent_order[item["job_url"]]
        if delta >= 0:
            continue
        lines.append(
            "- down {delta}: {label} | intent {intent_score:.1f} | simple {simplified_score:.1f} | {title} / {company}".format(
                delta=delta,
                **item,
            )
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate offline profile gold sets")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--labels-path")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output-dir")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    labels_path = (
        Path(args.labels_path).expanduser().resolve()
        if args.labels_path
        else DEFAULT_EVAL_DIR / f"{args.profile}_job_fit_gold.jsonl"
    )
    report = run_eval(args.profile, labels_path, args.top_k)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT
        / f"{args.profile}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output_dir / "summary.md").write_text(_render_summary(report) + "\n")
    print(json.dumps({"output_dir": str(output_dir), "rows": len(report["rows"])}))


if __name__ == "__main__":
    main()
