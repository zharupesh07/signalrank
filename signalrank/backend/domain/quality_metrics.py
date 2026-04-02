from __future__ import annotations

import math


def precision_at_k(relevant_ids: set[str], ranked_ids: list[str], k: int) -> float:
    """Fraction of top-k ranked results that are relevant (applied/interested)."""
    if not ranked_ids or k <= 0:
        return 0.0
    top_k = ranked_ids[:k]
    hits = sum(1 for job_id in top_k if job_id in relevant_ids)
    return hits / min(k, len(ranked_ids))


def ndcg(relevant_ids: set[str], ranked_ids: list[str], k: int | None = None) -> float:
    """Normalized Discounted Cumulative Gain.

    Binary relevance: 1 if job_id in relevant_ids, 0 otherwise.
    Returns float in [0, 1]. Returns 0.0 if no relevant items.
    """
    if not ranked_ids or not relevant_ids:
        return 0.0

    n = min(k, len(ranked_ids)) if k else len(ranked_ids)
    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, job_id in enumerate(ranked_ids[:n])
        if job_id in relevant_ids
    )
    # Ideal DCG: relevant items placed first
    ideal_hits = min(len(relevant_ids), n)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def skip_rate_in_top_k(skipped_ids: set[str], ranked_ids: list[str], k: int) -> float:
    """Fraction of top-k results that the user explicitly skipped/rejected."""
    if not ranked_ids or k <= 0:
        return 0.0
    top_k = ranked_ids[:k]
    skips = sum(1 for job_id in top_k if job_id in skipped_ids)
    return skips / min(k, len(ranked_ids))


def compute_metrics(
    *,
    applied_job_ids: list[str],
    skipped_job_ids: list[str],
    ranked_job_ids: list[str],
    k: int = 10,
) -> dict:
    """Compute all quality metrics for a single user ranking session."""
    applied = set(applied_job_ids)
    skipped = set(skipped_job_ids)
    return {
        "precision_at_k": precision_at_k(applied, ranked_job_ids, k),
        "ndcg": ndcg(applied, ranked_job_ids),
        "ndcg_at_k": ndcg(applied, ranked_job_ids, k),
        "skip_rate_at_k": skip_rate_in_top_k(skipped, ranked_job_ids, k),
        "total_ranked": len(ranked_job_ids),
        "total_applied": len(applied),
        "total_skipped": len(skipped),
        "k": k,
    }
