"""
Deterministic consensus labeler for benchmark snapshots.

This simulates the same control flow as an ensemble of judges:
agreement, split_resolved, unresolved, and fallback.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from tools.benchmark_ranking.score_labeled import _job_id

STATUS_AGREEMENT = "agreement"
STATUS_SPLIT_RESOLVED = "split_resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_FALLBACK = "fallback"


def _role_score(features: dict[str, float]) -> float:
    return 0.45 * features.get("role_family_match", 0.0) + 0.25 * features.get(
        "description_role_family_terms", 0.0
    )


def _core_score(features: dict[str, float]) -> float:
    return (
        0.30 * features.get("skill_overlap", 0.0)
        + 0.25 * features.get("must_have_hits", 0.0)
        + 0.15 * features.get("domain_match", 0.0)
        + 0.10 * max(0.0, features.get("seniority_match", 0.0))
        + 0.10 * features.get("title_similarity", 0.0)
    )


def _penalty_score(features: dict[str, float]) -> float:
    return 0.35 * features.get("negative_hits", 0.0) + 0.15 * max(
        0.0, -features.get("seniority_match", 0.0)
    )


def judge_strict(job: dict) -> str:
    features = job.get("features", {})
    role = _role_score(features)
    core = _core_score(features)
    penalty = _penalty_score(features)
    if penalty >= 0.25:
        return "bad"
    if role >= 0.45 and core >= 0.45:
        return "good"
    if role >= 0.20 or core >= 0.35:
        return "adjacent"
    return "bad"


def judge_balanced(job: dict) -> str:
    features = job.get("features", {})
    total = (
        0.25 * features.get("title_similarity", 0.0)
        + 0.25 * features.get("skill_overlap", 0.0)
        + 0.20 * features.get("must_have_hits", 0.0)
        + 0.15 * features.get("domain_match", 0.0)
        + 0.15 * features.get("role_family_match", 0.0)
        - 0.20 * features.get("negative_hits", 0.0)
    )
    if total >= 0.55:
        return "good"
    if total >= 0.28:
        return "adjacent"
    return "bad"


def judge_conservative(job: dict) -> str:
    features = job.get("features", {})
    if features.get("negative_hits", 0.0) >= 0.25:
        return "bad"
    if features.get("must_have_hits", 0.0) >= 0.5 and features.get("domain_match", 0.0) >= 1.0:
        return "good"
    if features.get("role_family_match", 0.0) >= 1.0 or features.get("skill_overlap", 0.0) >= 0.4:
        return "adjacent"
    return "bad"


def consensus_label(job: dict) -> dict[str, str]:
    first = judge_strict(job)
    second = judge_balanced(job)
    if first == second:
        return {"label": first, "status": STATUS_AGREEMENT}

    third = judge_conservative(job)
    counts = Counter([first, second, third])
    label, votes = counts.most_common(1)[0]
    if votes >= 2:
        return {"label": label, "status": STATUS_SPLIT_RESOLVED}

    features = job.get("features", {})
    evidence = max(
        _role_score(features),
        _core_score(features),
        1.0 - _penalty_score(features),
    )
    if evidence < 0.35:
        return {"label": "adjacent", "status": STATUS_FALLBACK}
    return {"label": "adjacent", "status": STATUS_UNRESOLVED}


def label_snapshot(snapshot: list[dict]) -> tuple[dict[str, str], Counter]:
    labels: dict[str, str] = {}
    statuses: Counter = Counter()
    for job in snapshot:
        result = consensus_label(job)
        labels[_job_id(job)] = result["label"]
        statuses[result["status"]] += 1
    return labels, statuses


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministically label a benchmark snapshot.")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--resume", required=True, type=str)
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if args.labels.exists():
        raw = args.labels.read_text(encoding="utf-8").strip()
        all_labels = json.loads(raw) if raw else {}
    else:
        all_labels = {}
    labels, statuses = label_snapshot(snapshot)
    all_labels[args.resume] = labels
    args.labels.write_text(json.dumps(all_labels, indent=2) + "\n", encoding="utf-8")

    print(f"Resume: {args.resume}")
    for key in (STATUS_AGREEMENT, STATUS_SPLIT_RESOLVED, STATUS_UNRESOLVED, STATUS_FALLBACK):
        print(f"{key}: {statuses.get(key, 0)}")


if __name__ == "__main__":
    main()
