from __future__ import annotations

from pathlib import Path

import yaml

from ranking.v3.features import compute_features
from ranking.v3.profile import ProfileV3

_WEIGHTS_PATH = Path(__file__).parent / "weights.yaml"


def load_weights(active_lanes: list[str] | None = None) -> dict[str, float]:
    """Load default weights from weights.yaml, apply lane overrides (replace, not add)."""
    raw = yaml.safe_load(_WEIGHTS_PATH.read_text())
    weights: dict[str, float] = dict(raw["defaults"])
    lane_overrides: dict[str, dict[str, float]] = raw.get("lane_overrides", {})

    for lane_name in (active_lanes or []):
        overrides = lane_overrides.get(lane_name, {})
        for feature, value in overrides.items():
            weights[feature] = value

    return weights


def score_job(job: dict, profile: ProfileV3) -> float:
    """Compute weighted score for a single job against a profile."""
    weights = load_weights(active_lanes=profile.active_lanes)
    features = compute_features(job, profile)
    return sum(features[feat] * weights.get(feat, 0.0) for feat in features)


def score_jobs(jobs: list[dict], profile: ProfileV3) -> list[dict]:
    """Score all jobs and return sorted list with score and features attached."""
    weights = load_weights(active_lanes=profile.active_lanes)
    results: list[dict] = []
    for job in jobs:
        features = compute_features(job, profile)
        total = sum(features[feat] * weights.get(feat, 0.0) for feat in features)
        results.append({**job, "score": total, "features": features})
    return sorted(results, key=lambda x: x["score"], reverse=True)
