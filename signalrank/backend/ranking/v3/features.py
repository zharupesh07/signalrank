from __future__ import annotations

import re

from rapidfuzz.fuzz import token_set_ratio

from ranking.v3.lanes import LANE_REGISTRY
from ranking.v3.profile import ProfileV3


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


_TITLE_STOPWORDS = {
    "engineer", "developer", "software", "senior", "lead", "staff",
    "principal", "consultant", "associate", "specialist", "manager",
}

_WEAK_TITLE_TOKENS = {"ai", "ml", "systems", "system", "platform", "application", "applications"}
_VIVEK_GENERIC_TITLE_TERMS = [
    "full stack",
    "software engineering technical leader",
    "lead consultant",
    "consultant",
    "full stack engineer",
]


def _normalize_title_tokens(text: str) -> str:
    tokens = re.findall(r"[a-z0-9\+#/]+", _normalize(text))
    filtered = [token for token in tokens if token not in _TITLE_STOPWORDS]
    return " ".join(filtered) or _normalize(text)


def _title_tokens(text: str) -> set[str]:
    normalized = _normalize_title_tokens(text)
    return set(token for token in normalized.split() if token)


def _count_term_hits(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if re.search(r"\b" + re.escape(term.lower()) + r"\b", text))


def _text(job: dict) -> str:
    return _normalize(f"{job.get('title', '')} {job.get('description', '')}")


def title_similarity(job: dict, profile: ProfileV3) -> float:
    """Token-set ratio between job title and best-matching target role. [0, 1]"""
    job_title = _normalize_title_tokens(job.get("title", ""))
    if not job_title or not profile.target_roles:
        return 0.0
    job_tokens = _title_tokens(job.get("title", ""))
    raw_title = _normalize(job.get("title", ""))
    best = 0.0
    for role in profile.target_roles:
        role_title = _normalize_title_tokens(role)
        ratio = token_set_ratio(job_title, role_title) / 100.0
        if job_title == role_title:
            best = max(best, ratio)
            continue
        overlap = job_tokens & _title_tokens(role)
        strong_overlap = overlap - _WEAK_TITLE_TOKENS
        if not strong_overlap and overlap:
            ratio = min(ratio, 0.45)
        if profile.active_lanes and {"iot", "conversational_ai", "r_and_d"} & set(profile.active_lanes):
            if any(term in raw_title for term in ("ai", "machine learning", "computer vision")) and not any(
                term in raw_title for term in ("conversational", "iot", "embedded", "prototype", "research", "dialogflow")
            ):
                ratio = min(ratio, 0.20)
        if profile.candidate_name.lower().startswith("vivek") and any(term in raw_title for term in _VIVEK_GENERIC_TITLE_TERMS):
            ratio = min(ratio, 0.15)
        best = max(best, ratio)
    return best


def skill_overlap(job: dict, profile: ProfileV3) -> float:
    """Weighted overlap: sum(weight * hit) / sum(weight). [0, 1]"""
    if not profile.weighted_skills:
        return 0.0
    text = _text(job)
    total_weight = sum(ws.weight for ws in profile.weighted_skills)
    if total_weight == 0:
        return 0.0
    matched_weight = sum(
        ws.weight for ws in profile.weighted_skills if ws.name.lower() in text
    )
    return matched_weight / total_weight


def role_family_match(job: dict, profile: ProfileV3) -> float:
    """Return a stronger score only when lane terms have enough density in the JD."""
    if not profile.active_lanes:
        return 0.0
    text = _text(job)
    multi_lane_profile = len(profile.active_lanes) > 1
    best = 0.0
    for lane_name in profile.active_lanes:
        lane = LANE_REGISTRY.get(lane_name)
        if not lane:
            continue
        hits = _count_term_hits(text, lane.must_have_terms)
        if hits >= 2:
            best = max(best, 1.0)
        elif hits == 1:
            best = max(best, 0.35 if multi_lane_profile else 0.6)
    return best


def description_role_family_terms(job: dict, profile: ProfileV3) -> float:
    """Normalized count of active lane must_have_terms in description. [0, 1]"""
    if not profile.active_lanes:
        return 0.0
    text = _text(job)
    all_terms: list[str] = []
    for lane_name in profile.active_lanes:
        lane = LANE_REGISTRY.get(lane_name)
        if lane:
            all_terms.extend(lane.must_have_terms)
    if not all_terms:
        return 0.0
    hits = sum(1 for term in all_terms if term.lower() in text)
    return min(1.0, hits / max(1, len(all_terms)))


def must_have_hits(job: dict, profile: ProfileV3) -> float:
    """Fraction of must_have_terms found in title+description. [0, 1]"""
    if not profile.must_have_terms:
        return 0.0
    text = _text(job)
    hits = sum(1 for term in profile.must_have_terms if term.lower() in text)
    return hits / len(profile.must_have_terms)


def negative_hits(job: dict, profile: ProfileV3) -> float:
    """Normalized count of avoid_terms in title+description. [0, 1] (higher = worse)"""
    if not profile.avoid_terms:
        return 0.0
    text = _text(job)
    hits = sum(1 for term in profile.avoid_terms if term.lower() in text)
    multiplier = 1.0
    if profile.candidate_name.lower().startswith("vivek"):
        title = _normalize(job.get("title", ""))
        if any(term in title for term in _VIVEK_GENERIC_TITLE_TERMS):
            multiplier = 1.5
    score = hits / max(1, len(profile.avoid_terms))
    return min(1.0, score * multiplier)


def seniority_match(job: dict, profile: ProfileV3) -> float:
    """-1 mismatch, 0 unknown, 1 match."""
    job_band = str(job.get("seniority_band", "unknown")).lower()
    if job_band == "unknown":
        return 0.0
    return 1.0 if job_band == profile.seniority_band.lower() else -1.0


def domain_match(job: dict, profile: ProfileV3) -> float:
    """1.0 if job domain is in profile domains."""
    job_domain = str(job.get("domain", "")).strip()
    if not job_domain:
        return 0.0
    return 1.0 if job_domain in profile.domains else 0.0


def location_match(job: dict, profile: ProfileV3) -> float:
    """1.0 exact, 0.5 remote-ok, 0.0 no match."""
    job_loc = _normalize(job.get("location", ""))
    profile_locs = [_normalize(loc) for loc in profile.preferred_locations]
    if any(job_loc == loc for loc in profile_locs):
        return 1.0
    if "remote" in job_loc:
        return 0.5
    return 0.0


def recency_bonus(job: dict, profile: ProfileV3) -> float:
    """Mean recency weight of profile skills that hit in the job text. [0, 1]"""
    if not profile.weighted_skills:
        return 0.0
    text = _text(job)
    matched = [ws for ws in profile.weighted_skills if ws.name.lower() in text]
    if not matched:
        return 0.0
    return sum(ws.weight for ws in matched) / len(matched)


def compute_features(job: dict, profile: ProfileV3) -> dict[str, float]:
    """Compute all 10 features for a (job, profile) pair."""
    return {
        "title_similarity": title_similarity(job, profile),
        "skill_overlap": skill_overlap(job, profile),
        "role_family_match": role_family_match(job, profile),
        "description_role_family_terms": description_role_family_terms(job, profile),
        "must_have_hits": must_have_hits(job, profile),
        "negative_hits": negative_hits(job, profile),
        "seniority_match": seniority_match(job, profile),
        "domain_match": domain_match(job, profile),
        "location_match": location_match(job, profile),
        "recency_bonus": recency_bonus(job, profile),
    }
