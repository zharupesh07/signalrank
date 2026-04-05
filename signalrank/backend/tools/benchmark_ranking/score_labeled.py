"""
Compute precision@K and nDCG@20 from a snapshot and labels.json.

Usage:
    uv run python tools/benchmark_ranking/score_labeled.py \
        --snapshot snapshots/candidate_<sha>_example.json \
        --labels labels/labels.json \
        --resume example
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

RELEVANCE = {"good": 1.0, "adjacent": 0.5, "bad": 0.0}


def _job_id(job: dict) -> str:
    return str(job.get("id") or job.get("job_url") or job.get("url") or job.get("title") or "")


def precision_at_k(ranked: list[dict], labels: dict[str, str], k: int) -> float:
    window = ranked[:k]
    labeled = [job for job in window if labels.get(_job_id(job), "unlabeled") != "unlabeled"]
    if not labeled:
        return 0.0
    score = sum(RELEVANCE.get(labels.get(_job_id(job), "bad"), 0.0) for job in labeled)
    return score / len(labeled)


def ndcg_at_k(ranked: list[dict], labels: dict[str, str], k: int) -> float:
    def dcg(items: list[dict]) -> float:
        total = 0.0
        for idx, job in enumerate(items[:k], start=1):
            rel = RELEVANCE.get(labels.get(_job_id(job), "unlabeled"), 0.0)
            total += rel / math.log2(idx + 1)
        return total

    actual = dcg(ranked)
    ideal = sorted(
        ranked[:k],
        key=lambda job: RELEVANCE.get(labels.get(_job_id(job), "unlabeled"), 0.0),
        reverse=True,
    )
    ideal_score = dcg(ideal)
    if ideal_score <= 0:
        return 0.0
    return actual / ideal_score


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a ranked snapshot against benchmark labels.")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--resume", required=True, type=str)
    args = parser.parse_args()

    ranked = json.loads(args.snapshot.read_text(encoding="utf-8"))
    all_labels: dict[str, dict[str, str]] = json.loads(args.labels.read_text(encoding="utf-8"))
    labels = all_labels.get(args.resume, {})

    unlabeled = [_job_id(job) for job in ranked[:30] if labels.get(_job_id(job), "unlabeled") == "unlabeled"]

    print(f"Resume: {args.resume}")
    print(f"Precision@10:  {precision_at_k(ranked, labels, 10):.3f}")
    print(f"Precision@20:  {precision_at_k(ranked, labels, 20):.3f}")
    print(f"Precision@30:  {precision_at_k(ranked, labels, 30):.3f}")
    print(f"nDCG@20:       {ndcg_at_k(ranked, labels, 20):.3f}")
    if unlabeled:
        print(f"\nUnlabeled jobs in top-30 ({len(unlabeled)})")
        for job_id in unlabeled:
            print(f"  {job_id}")


if __name__ == "__main__":
    main()
