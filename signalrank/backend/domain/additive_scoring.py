# domain/additive_scoring.py
"""
Weighted additive scoring: 5 dimensions each scored 0-100.

final_score = skills × 0.40 + company × 0.20 + seniority × 0.15
            + location × 0.15 + recency × 0.10
"""

from __future__ import annotations

from datetime import datetime, timezone


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(value, hi))


def skills_score_0_100(
    semantic_score: float,
    skill_overlap: int,
    role_skill_score: float,
    functional_role_penalty: float,
    consulting_damp: float,
) -> float:
    base = semantic_score * 100

    # Skill overlap bonus (capped at +8)
    base += min(skill_overlap * 2, 8)

    # Role/skill modifier: clamped [-10, +10]
    role_mod = (role_skill_score - 1.0) * 25
    base += _clamp(role_mod, -10, 10)

    # Functional role modifier: clamped [-8, +10]
    func_mod = (functional_role_penalty - 1.0) * 50
    base += _clamp(func_mod, -8, 10)

    # Consulting dampener: if < 1.0, subtract 10
    if consulting_damp < 1.0:
        base -= 10

    return _clamp(base)


def company_score_0_100(tier: str) -> float:
    return {
        "tier_ss": 100.0,
        "tier_s": 95.0,
        "tier_a": 85.0,
        "tier_b": 65.0,
        "tier_c": 45.0,
        "tier_d": 15.0,
        # Legacy compatibility
        "preferred": 100.0,
        "deprioritized": 15.0,
    }.get(tier, 40.0)


def apply_company_semantic_floor(
    company_score: float, semantic_score: float, floor: float
) -> float:
    """Scale down company_score when semantic_score is below the floor."""
    if floor <= 0:
        return company_score
    if semantic_score >= floor:
        return company_score
    return company_score * (semantic_score / floor)


def apply_hidden_gem_bonus(
    company_score: float, tier: str, semantic_score: float,
    threshold: float = 0.70, bonus_score: float = 60.0,
) -> float:
    """Bump company_score for unknown-tier jobs with high semantic fit."""
    if tier not in ("default", "") and tier is not None:
        return company_score
    if semantic_score >= threshold:
        return max(company_score, bonus_score)
    return company_score


def seniority_score_0_100(multiplier: float) -> float:
    # Linear map [0.4, 1.15] -> [10, 100]
    score = ((multiplier - 0.4) / 0.75) * 90 + 10
    return _clamp(score)


def location_score_0_100(weight: float) -> float:
    return 100.0 if weight > 1.0 else 30.0


def recency_score_0_100(date_posted) -> float:
    if date_posted is None:
        return 30.0

    try:
        posted = datetime.fromisoformat(str(date_posted).replace("Z", "+00:00"))
        # Ensure timezone-aware comparison
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - posted).days
    except Exception:
        return 30.0

    if age_days < 0:
        return 100.0

    # Piecewise linear: 0d->100, 7d->80, 14d->60, 30d->30, 60d->10
    breakpoints = [(0, 100), (7, 80), (14, 60), (30, 30), (60, 10)]
    for i in range(len(breakpoints) - 1):
        d0, s0 = breakpoints[i]
        d1, s1 = breakpoints[i + 1]
        if age_days <= d1:
            frac = (age_days - d0) / (d1 - d0)
            return s0 + frac * (s1 - s0)

    return 10.0


CONTRACT_SIGNALS = [
    "contract", "part-time", "part time", "freelance",
    "hours per day", "hrs/day", "hours/day", "hrs per day",
    "hr/day", "hr per day",
    "temporary", "temp position", "fixed-term", "fixed term",
]


def detect_contract_type(title: str, description: str) -> bool:
    """Return True if the job appears to be contract/part-time."""
    title_lower = (title or "").lower()
    desc_prefix = (description or "")[:200].lower()
    # Strip backslash escapes (common in markdown-formatted descriptions)
    text = f"{title_lower} {desc_prefix}".replace("\\", "")
    return any(signal in text for signal in CONTRACT_SIGNALS)


_REMOTE_LOCATION_SIGNALS = [
    "remote", "work from home", "wfh", "anywhere",
]

_REMOTE_DESCRIPTION_SIGNALS = [
    "fully remote", "100% remote", "work from home", "wfh",
    "remote position", "remote role", "remote working", "remote first",
    "remote-first", "work remotely", "fully distributed",
]

_HYBRID_SIGNALS = [
    "hybrid", "2 days", "3 days", "days in office", "days per week",
    "flexible work", "flexible arrangement", "partially remote",
]


def detect_work_mode(location: str, title: str, description: str) -> str:
    """Classify work mode as 'remote', 'hybrid', 'onsite', or 'unknown'.

    Priority: remote > hybrid > onsite > unknown.
    Returns 'unknown' when there is insufficient signal (no location, no description signals).
    """
    if not location and not title and not description:
        return "unknown"

    loc = (location or "").lower().strip()
    desc_prefix = (description or "")[:500].lower()

    if any(s in loc for s in _REMOTE_LOCATION_SIGNALS):
        return "remote"

    if any(s in desc_prefix for s in _REMOTE_DESCRIPTION_SIGNALS):
        return "remote"

    if any(s in desc_prefix for s in _HYBRID_SIGNALS):
        return "hybrid"

    if loc:
        return "onsite"

    return "unknown"


DEFAULT_WEIGHTS = {
    "skills_match": 0.40,
    "company_fit": 0.20,
    "seniority": 0.15,
    "location": 0.15,
    "recency": 0.10,
}


def compute_weighted_score(scores: dict[str, float], weights: dict[str, float] | None = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    return (
        scores["skills_match"] * w.get("skills_match", 0.40)
        + scores["company_fit"] * w.get("company_fit", 0.20)
        + scores["seniority"] * w.get("seniority", 0.15)
        + scores["location"] * w.get("location", 0.15)
        + scores["recency"] * w.get("recency", 0.10)
    )
