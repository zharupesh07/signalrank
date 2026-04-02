from __future__ import annotations

import numpy as np

from domain.embed_math import cosine_similarity


def compute_title_relevance(
    job_titles: list[str],
    target_role_embeddings: np.ndarray,
) -> np.ndarray:
    """Return per-job max cosine similarity of job title embedding against target role embeddings.

    Args:
        job_titles: Already-embedded job title vectors, shape (n_jobs, dim).
        target_role_embeddings: Target role vectors, shape (n_roles, dim).

    Returns:
        np.ndarray of shape (n_jobs,) in [-1, 1].
        If no target roles provided, returns ones (no penalty).
    """
    if target_role_embeddings is None or len(target_role_embeddings) == 0:
        return np.ones(len(job_titles), dtype="float32")
    if len(job_titles) == 0:
        return np.array([], dtype="float32")

    title_matrix = np.array(job_titles, dtype="float32")  # (n_jobs, dim)
    role_matrix = np.array(target_role_embeddings, dtype="float32")  # (n_roles, dim)

    # For each target role, compute cosine similarity against all job titles
    # cosine_similarity(query, matrix) → shape (n_jobs,)
    sims = np.stack(
        [cosine_similarity(role_vec, title_matrix) for role_vec in role_matrix],
        axis=1,
    )  # (n_jobs, n_roles)
    return sims.max(axis=1)  # (n_jobs,) — best match across all target roles


def title_relevance_score_0_100(
    similarity: float | np.ndarray,
    low: float = 0.25,
    high: float = 0.90,
) -> float | np.ndarray:
    """Linear map [low, high] → [0, 100]. Clipped at boundaries."""
    score = (np.asarray(similarity, dtype="float32") - low) / (high - low) * 100.0
    return np.clip(score, 0.0, 100.0)
