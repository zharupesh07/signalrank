from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from domain.job_source import compute_freshness_bucket, is_aggregator_source, parse_datetime, source_priority
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
    bucket = compute_freshness_bucket(job.get("date_posted"), job.get("ingested_at"), job.get("site"))
    if bucket == "stale":
        return True
    posted = parse_datetime(job.get("date_posted"))
    if posted is None:
        return False
    return (datetime.now(tz=timezone.utc) - posted).days > _STALENESS_DAYS


def _dedup_key(job: dict) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", (job.get("title") or "").lower().strip())
    company = re.sub(r"\s+", " ", (job.get("company") or "").lower().strip())
    return (title, company)


def _job_rank_tuple(job: dict) -> tuple[int, str, str, int]:
    posted = parse_datetime(job.get("date_posted"))
    ingested = parse_datetime(job.get("ingested_at"))
    return (
        source_priority(job.get("site")),
        posted.isoformat() if posted else "",
        ingested.isoformat() if ingested else "",
        len(str(job.get("description") or "")),
    )


def _dedup_jobs(jobs: list[dict]) -> list[dict]:
    """Keep best posting per (title_normalized, company_normalized)."""
    seen: dict[tuple[str, str], dict] = {}
    for job in jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen[key] = job
        else:
            if _job_rank_tuple(job) > _job_rank_tuple(seen[key]):
                seen[key] = job
    return list(seen.values())


def _precision_penalty_multiplier(job: dict, profile: CandidateProfile, features: dict[str, float]) -> tuple[float, list[str]]:
    multiplier = 1.0
    reasons: list[str] = []
    title = str(job.get("title") or "").lower()
    bucket = compute_freshness_bucket(job.get("date_posted"), job.get("ingested_at"), job.get("site"))

    if features["title_similarity"] < 0.22 and features["must_have_hits"] == 0 and features["role_family_match"] == 0:
        multiplier *= 0.55
        reasons.append("Weak title-role match")

    if features["role_shape_match"] <= 0.2:
        multiplier *= 0.45
        reasons.append("Role shape drift")

    if "software engineer" in title and features["role_shape_match"] < 0.4 and features["must_have_hits"] < 0.15:
        multiplier *= 0.52
        reasons.append("Generic software role")

    if features["negative_hits"] >= 0.20:
        multiplier *= 0.58
        reasons.append("Avoid terms in title or description")

    if any(token in title for token in ("intern", "junior", "associate", "entry")) and profile.seniority_band.lower() in {"senior", "principal"}:
        multiplier *= 0.62
        reasons.append("Junior mismatch")

    if features["seniority_match"] < 0:
        multiplier *= 0.65
        reasons.append("Seniority mismatch")

    if features["location_match"] == 0.0 and profile.preferred_locations:
        multiplier *= 0.55
        reasons.append("Location mismatch")

    if features["description_quality"] <= 0.2:
        multiplier *= 0.72
        reasons.append("Thin description quality")

    if bucket == "stale":
        multiplier *= 0.7
        reasons.append("Stale posting")

    if features["company_tier_score"] >= 0.85 and features["semantic_similarity"] < 0.16 and features["title_similarity"] < 0.38:
        multiplier *= 0.78
        reasons.append("Brand strong, fit weak")

    if is_aggregator_source(job.get("site")):
        if features["must_have_hits"] < 0.25 and features["role_shape_match"] < 0.85:
            multiplier *= 0.7
            reasons.append("Aggregator source with limited fit evidence")
        elif features["title_similarity"] < 0.7 and features["skill_overlap"] < 0.2:
            multiplier *= 0.82
            reasons.append("Aggregator source without strong role evidence")

    return multiplier, reasons


def _rank_reason_up(features: dict[str, float], job: dict) -> list[str]:
    reasons: list[str] = []
    if features["title_similarity"] >= 0.78:
        reasons.append("Strong title match")
    if features["role_shape_match"] >= 0.8:
        reasons.append("Good role shape")
    if features["must_have_hits"] >= 0.5:
        reasons.append("Must-have skills present")
    if features["skill_overlap"] >= 0.55:
        reasons.append("High skill overlap")
    if features["role_family_match"] >= 0.9:
        reasons.append("Same role family")
    if features["location_match"] >= 1.0:
        reasons.append("Preferred location")
    if features["source_quality"] >= 1.0:
        reasons.append("Direct ATS source")
    if features["recency_score"] >= 0.75:
        reasons.append("Fresh posting")
    return reasons[:3]


def score_job(job: dict, profile: CandidateProfile, weights: dict[str, float]) -> float:
    """Compute weighted score for a single job."""
    features = compute_features(job, profile)
    return sum(features[feat] * weights.get(feat, 0.0) for feat in features)


def score_jobs(jobs: list[dict], profile: CandidateProfile, *, dedupe: bool = True) -> list[dict]:
    """Score all jobs, deduplicate by (title, company), return sorted list.

    Scores are normalized to [0, 1] against the theoretical maximum (sum of
    positive weights), not relative to the batch top. This ensures a score of
    1.0 means a perfect match, not just "best in a bad batch".
    """
    weights = load_weights(active_lanes=profile.active_lanes)
    max_possible = sum(w for w in weights.values() if w > 0) or 1.0
    if dedupe:
        jobs = _dedup_jobs(jobs)
    results: list[dict] = []
    for job in jobs:
        features = compute_features(job, profile)
        total = sum(features[feat] * weights.get(feat, 0.0) for feat in features)
        normalized = max(0.0, min(1.0, total / max_possible))
        penalty_multiplier, penalty_reasons = _precision_penalty_multiplier(job, profile, features)
        adjusted = max(0.0, min(1.0, normalized * penalty_multiplier))
        results.append({
            **job,
            "score": adjusted,
            "features": features,
            "rank_reason_up": _rank_reason_up(features, job),
            "rank_reason_down": penalty_reasons,
            "rank_stage": "deterministic",
            "freshness_bucket": compute_freshness_bucket(job.get("date_posted"), job.get("ingested_at"), job.get("site")),
        })
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

    profile_dict = dataclasses.asdict(profile)
    for r in scored:
        r["profile"] = profile_dict

    return scored[:top_k]
