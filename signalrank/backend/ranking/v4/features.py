from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
from rapidfuzz.fuzz import token_set_ratio

from ranking.v4.lanes import LANE_REGISTRY
from ranking.v4.profile import CandidateProfile

if TYPE_CHECKING:
    pass

_COMPANY_TIER_SCORES: dict[str, float] = {
    "tier_ss": 1.00,
    "tier_s": 0.95,
    "tier_a": 0.85,
    "tier_b": 0.65,
    "tier_c": 0.45,
    "tier_d": 0.15,
    "preferred": 1.00,
    "deprioritized": 0.15,
}
_DEFAULT_COMPANY_SCORE = 0.40

_SENIORITY_TITLE_PATTERNS: list[tuple[list[str], str]] = [
    (["principal", "distinguished", "architect", "head of"], "principal"),
    (["staff", "lead", "manager", "director", "vp", "vice president"], "senior"),
    (["senior", "sr.", "sr "], "senior"),
    (["junior", "entry", "associate", "intern", "entry-level"], "junior"),
]

_TITLE_STOPWORDS = {
    "engineer", "developer", "software", "senior", "lead", "staff",
    "principal", "consultant", "associate", "specialist", "manager",
}

_WEAK_TITLE_TOKENS = {"ai", "ml", "systems", "system", "platform", "application", "applications"}


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _normalize_title_tokens(text: str) -> str:
    tokens = re.findall(r"[a-z0-9\+#/]+", _normalize(text))
    filtered = [t for t in tokens if t not in _TITLE_STOPWORDS]
    return " ".join(filtered) or _normalize(text)


def _title_tokens(text: str) -> set[str]:
    return set(t for t in _normalize_title_tokens(text).split() if t)


def _count_term_hits(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if re.search(r"\b" + re.escape(term.lower()) + r"\b", text))


def _job_text(job: dict) -> str:
    return _normalize(f"{job.get('title', '')} {job.get('description', '')}")


def _infer_job_seniority(title: str) -> str:
    t = (title or "").lower()
    for keywords, band in _SENIORITY_TITLE_PATTERNS:
        if any(kw in t for kw in keywords):
            return band
    return "mid"


# ─── Feature Functions ────────────────────────────────────────────────────────

def title_similarity(job: dict, profile: CandidateProfile) -> float:
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
        best = max(best, ratio)
    return best


def skill_overlap(job: dict, profile: CandidateProfile) -> float:
    """Weighted overlap: sum(weight * hit) / sum(weight). [0, 1]"""
    if not profile.weighted_skills:
        return 0.0
    text = _job_text(job)
    total_weight = sum(ws.weight for ws in profile.weighted_skills)
    if total_weight == 0:
        return 0.0
    matched_weight = sum(ws.weight for ws in profile.weighted_skills if ws.name.lower() in text)
    return matched_weight / total_weight


def role_family_match(job: dict, profile: CandidateProfile) -> float:
    """Return stronger score when lane terms have enough density in the JD. [0, 1]"""
    if not profile.active_lanes:
        return 0.0
    text = _job_text(job)
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


def description_role_family_terms(job: dict, profile: CandidateProfile) -> float:
    """Normalized count of active lane must_have_terms in description. [0, 1]"""
    if not profile.active_lanes:
        return 0.0
    text = _job_text(job)
    all_terms: list[str] = []
    for lane_name in profile.active_lanes:
        lane = LANE_REGISTRY.get(lane_name)
        if lane:
            all_terms.extend(lane.must_have_terms)
    if not all_terms:
        return 0.0
    hits = sum(1 for term in all_terms if term.lower() in text)
    return min(1.0, hits / max(1, len(all_terms)))


def must_have_hits(job: dict, profile: CandidateProfile) -> float:
    """Fraction of must_have_terms found in title+description. [0, 1]"""
    if not profile.must_have_terms:
        return 0.0
    text = _job_text(job)
    hits = sum(1 for term in profile.must_have_terms if term.lower() in text)
    return hits / len(profile.must_have_terms)


def negative_hits(job: dict, profile: CandidateProfile) -> float:
    """Fraction of avoid_terms found in title+description. [0, 1] (higher = worse match)"""
    if not profile.avoid_terms:
        return 0.0
    text = _job_text(job)
    hits = sum(1 for term in profile.avoid_terms if term.lower() in text)
    return min(1.0, hits / max(1, len(profile.avoid_terms)))


def seniority_match(job: dict, profile: CandidateProfile) -> float:
    """[-1, 1] — title-inferred seniority vs candidate band. 0 when unknown/mid."""
    job_band = _infer_job_seniority(job.get("title") or "")
    if job_band == "mid":
        return 0.0
    return 1.0 if job_band == profile.seniority_band.lower() else -1.0


def location_match(job: dict, profile: CandidateProfile) -> float:
    """[0, 1] — 1.0 exact, 0.5 remote-ok, 0.0 no match."""
    job_loc = _normalize(job.get("location", ""))
    profile_locs = [_normalize(loc) for loc in profile.preferred_locations]
    if any(job_loc == loc for loc in profile_locs):
        return 1.0
    if "remote" in job_loc:
        return 0.5
    return 0.0


def recency_score(job: dict, profile: CandidateProfile) -> float:
    """Recency of job posting normalized to [0, 1]."""
    from domain.additive_scoring import recency_score_0_100
    return recency_score_0_100(job.get("date_posted")) / 100.0


def company_tier_score(job: dict, profile: CandidateProfile) -> float:
    """Company tier lookup, normalized to [0, 1].

    Checks job['company_tier'] (pre-computed at ingest via job_profile JSONB),
    then profile.company_tier_map, then falls back to _DEFAULT_COMPANY_SCORE.
    """
    tier = (job.get("company_tier") or "").lower().strip()
    if not tier and job.get("job_profile"):
        jp = job.get("job_profile") or {}
        tier = (jp.get("company_tier") or "").lower().strip()
    if not tier and profile.company_tier_map:
        company = _normalize(job.get("company", ""))
        tier = profile.company_tier_map.get(company, "")
    return _COMPANY_TIER_SCORES.get(tier, _DEFAULT_COMPANY_SCORE)


def semantic_similarity(job: dict, profile: CandidateProfile) -> float:
    """Cosine similarity between resume and job embeddings. [0, 1].

    Returns 0.0 when either embedding is unavailable (graceful degradation
    for V4 running without DB embeddings, e.g. in benchmark/CLI mode).
    """
    resume_emb = profile.resume_embedding
    job_emb = job.get("embedding")

    if resume_emb is None or job_emb is None:
        return 0.0

    r = np.array(resume_emb, dtype="float32")
    j = np.array(job_emb, dtype="float32")

    r_norm = np.linalg.norm(r)
    j_norm = np.linalg.norm(j)
    if r_norm == 0 or j_norm == 0:
        return 0.0

    cos_sim = float(np.dot(r, j) / (r_norm * j_norm))
    return max(0.0, min(1.0, cos_sim))


def description_quality(job: dict, profile: CandidateProfile) -> float:
    """Simple quality signal: penalize very short or boilerplate descriptions. [0, 1]"""
    desc = job.get("description") or ""
    length = len(desc)
    if length < 100:
        return 0.1
    if length < 300:
        return 0.5
    return 1.0


def compute_features(job: dict, profile: CandidateProfile) -> dict[str, float]:
    """Compute all 12 features for a (job, profile) pair."""
    return {
        "title_similarity": title_similarity(job, profile),
        "skill_overlap": skill_overlap(job, profile),
        "role_family_match": role_family_match(job, profile),
        "description_role_family_terms": description_role_family_terms(job, profile),
        "must_have_hits": must_have_hits(job, profile),
        "negative_hits": negative_hits(job, profile),
        "seniority_match": seniority_match(job, profile),
        "location_match": location_match(job, profile),
        "recency_score": recency_score(job, profile),
        "company_tier_score": company_tier_score(job, profile),
        "semantic_similarity": semantic_similarity(job, profile),
        "description_quality": description_quality(job, profile),
    }
