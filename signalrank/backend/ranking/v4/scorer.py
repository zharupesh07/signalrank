from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ranking.v4.features import compute_features
from ranking.v4.profile import CandidateProfile

_WEIGHTS_PATH = Path(__file__).parent / "weights.yaml"
_STALENESS_DAYS = 90


def load_weights(active_lanes: list[str] | None = None) -> dict[str, float]:
    """Load default weights, apply per-lane overrides (replace, not add)."""
    raw = yaml.safe_load(_WEIGHTS_PATH.read_text())
    weights: dict[str, float] = dict(raw["defaults"])
    lane_overrides: dict[str, dict[str, float]] = raw.get("lane_overrides", {})
    for lane_name in (active_lanes or []):
        for feature, value in lane_overrides.get(lane_name, {}).items():
            weights[feature] = value
    return weights


def _is_stale(job: dict) -> bool:
    date_str = job.get("date_posted")
    if not date_str:
        return False
    try:
        posted = datetime.fromisoformat(str(date_str)).replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - posted).days > _STALENESS_DAYS
    except ValueError:
        return False


def _dedup_key(job: dict) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", (job.get("title") or "").lower().strip())
    company = re.sub(r"\s+", " ", (job.get("company") or "").lower().strip())
    return (title, company)


def _dedup_jobs(jobs: list[dict]) -> list[dict]:
    """Keep most recent posting per (title_normalized, company_normalized)."""
    seen: dict[tuple[str, str], dict] = {}
    for job in jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen[key] = job
        else:
            if (job.get("date_posted") or "") > (seen[key].get("date_posted") or ""):
                seen[key] = job
    return list(seen.values())


def score_job(job: dict, profile: CandidateProfile, weights: dict[str, float]) -> float:
    """Compute weighted score for a single job."""
    features = compute_features(job, profile)
    return sum(features[feat] * weights.get(feat, 0.0) for feat in features)


def score_jobs(jobs: list[dict], profile: CandidateProfile) -> list[dict]:
    """Score all jobs, deduplicate, return sorted list with score and features."""
    weights = load_weights(active_lanes=profile.active_lanes)
    results: list[dict] = []
    for job in jobs:
        features = compute_features(job, profile)
        total = sum(features[feat] * weights.get(feat, 0.0) for feat in features)
        results.append({**job, "score": total, "features": features})
    return sorted(results, key=lambda x: x["score"], reverse=True)


def rank_jobs_v4(
    resume_text: str,
    jobs: list[dict],
    *,
    current_focus: str | None = None,
    config_overrides: dict | None = None,
    top_k: int = 30,
) -> list[dict]:
    """Standalone V4 pipeline (no DB): resume text + jobs list → sorted top-k.

    Each result contains original job fields plus:
      - score: float (normalized to [0, 1] relative to top result)
      - features: dict[str, float]
      - profile: dict (serialized CandidateProfile for audit)
    """
    import dataclasses
    from ranking.v4.extraction import extract_profile_v4

    profile = extract_profile_v4(
        resume_text,
        current_focus=current_focus,
        config_overrides=config_overrides,
    )
    fresh = _dedup_jobs([j for j in jobs if not _is_stale(j)])
    scored = score_jobs(fresh, profile)

    # Normalize to [0, 1] relative to top result
    if scored:
        max_score = scored[0]["score"]
        if max_score > 0:
            for r in scored:
                r["score"] = r["score"] / max_score

    profile_dict = dataclasses.asdict(profile)
    for r in scored:
        r["profile"] = profile_dict

    return scored[:top_k]
