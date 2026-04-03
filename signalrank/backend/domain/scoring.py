# domain/scoring.py
import math
import re
from datetime import datetime, timezone

# domain/scoring.py

from domain.additive_scoring import location_score_5tier


def recency_weight(cfg, date_posted):
    ranking = cfg.get("ranking", {})
    if ranking.get("recency_half_life_days", 0) <= 0:
        return 1.0
    if not ranking.get("enable_recency_decay", False):
        return 1.0

    if not date_posted:
        return 1.0

    try:
        posted = datetime.fromisoformat(str(date_posted).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - posted).days
        half_life = ranking.get("recency_half_life_days", 21)
        return math.exp(-age / half_life)
    except Exception:
        return 1.0


def calculate_seniority_score(
    cfg: dict,
    *,
    title: str,
    description: str,
    user_yoe: int | None = None,
) -> float:
    """
    Returns a bounded seniority multiplier in [0.4, 1.15].

    Philosophy:
    - Junior roles are penalized
    - Senior-aligned roles get a mild boost
    - Never dominates semantic intent
    """

    ranking = cfg.get("ranking", {})
    scfg = ranking.get("seniority_penalty", {})

    t = (title or "").lower()
    d = (description or "").lower()

    # --------------------
    # Junior hard penalties
    # --------------------
    junior_terms = scfg.get("title_keywords", {}).get("junior", [])
    if any(k in t for k in junior_terms):
        return scfg.get("junior_multiplier", 0.4)

    if any(x in d for x in ["0-2 years", "1-2 years", "2-3 years"]):
        return scfg.get("low_yoe_multiplier", 0.5)

    # --------------------
    # Over-senior penalties
    # --------------------
    over_senior_terms = scfg.get("title_keywords", {}).get("over_senior", [])
    if any(k in t for k in over_senior_terms):
        return scfg.get("over_senior_multiplier", 0.7)

    # --------------------
    # Senior / lead boosts
    # --------------------
    senior_terms = ranking.get(
        "seniority_boosting_keywords",
        ["senior", "lead", "staff", "principal"],
    )

    boost = 1.0
    if any(k in t for k in senior_terms):
        boost *= 1.08

    # --------------------
    # YOE alignment (soft)
    # --------------------
    if user_yoe is not None:
        req = extract_required_yoe(d)
        if req is not None:
            diff = abs(req - user_yoe)
            if diff <= 1:
                boost *= 1.05
            elif diff >= 5:
                boost *= 0.9

    return min(boost, 1.15)


def calculate_role_and_skill_match_score(
    cfg: dict,
    *,
    title: str,
    description: str,
) -> float:
    """
    Strong intent signal.
    This is NOT semantic similarity.
    Multiplier range: [0.6, 1.4]
    """

    ranking = cfg.get("ranking", {})
    text = f"{title} {description}".lower()

    score = 1.0

    # --------------------
    # Positive intent boosts
    # --------------------
    positives = ranking.get("positive_skill_keywords", {})
    for kw, weight in positives.items():
        if kw in text:
            score *= weight

    # --------------------
    # Negative intent penalties
    # --------------------
    negatives = ranking.get("negative_role_keywords", {})
    for kw, penalty in negatives.items():
        if kw in text:
            score *= penalty

    return max(0.6, min(score, 1.4))


def location_weight(location: str, cfg: dict) -> float:
    loc_cfg = cfg.get("location_scoring", {})
    preferred = loc_cfg.get("preferred_locations", [])
    boost = float(loc_cfg.get("preferred_weight", 1.0))

    if not location or not preferred:
        return 1.0

    loc = location.lower()
    for p in preferred:
        if isinstance(p, str) and p.lower() in loc:
            return boost

    return 1.0


def location_tier(location: str, description: str, cfg: dict) -> int:
    """Return a user-aware location score on a 0-100 gradient."""
    return location_score_5tier(location, description, cfg)


def extract_required_yoe(text: str) -> int | None:
    """
    Extract maximum years-of-experience required by a job.

    Returns:
      - highest YOE mentioned (int)
      - None if no requirement detected

    Conservative by design.
    """
    if not isinstance(text, str):
        return None

    t = text.lower()

    patterns = [
        r"(\d+)\s*\+?\s*years",
        r"(\d+)\s*-\s*(\d+)\s*years",
        r"minimum\s+(\d+)\s*years",
        r"at\s+least\s+(\d+)\s*years",
    ]

    found = []

    for p in patterns:
        for m in re.findall(p, t):
            if isinstance(m, tuple):
                nums = [int(x) for x in m if x.isdigit()]
                found.extend(nums)
            elif str(m).isdigit():
                found.append(int(m))

    if not found:
        return None

    return max(found)
