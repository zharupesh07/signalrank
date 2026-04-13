from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
from rapidfuzz.fuzz import token_set_ratio

from domain.job_source import is_direct_source, parse_datetime, source_quality_score
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
_LOCATION_ALIASES = {
    "bangalore": {"bangalore", "bengaluru", "ka", "karnataka", "ka in"},
    "bengaluru": {"bangalore", "bengaluru", "ka", "karnataka", "ka in"},
    "pune": {"pune", "mh", "maharashtra", "mh in"},
    "mumbai": {"mumbai", "bombay", "mh", "maharashtra", "mh in"},
    "hyderabad": {"hyderabad", "telangana", "ts", "ts in"},
    "chennai": {"chennai", "tn", "tamil nadu", "tn in"},
}
_ROLE_SHAPE_HARD_NEGATIVES = (
    "product manager",
    "program manager",
    "marketing",
    "account executive",
    "sales",
    "recruiter",
    "customer success",
    "designer",
)
_ROLE_SHAPE_ARCHITECT = ("architect", "solutions architect", "solution architect")
_ROLE_SHAPE_ADJACENT = (
    "solutions engineer",
    "forward deployed engineer",
    "customer engineer",
    "implementation engineer",
    "applied ai",
)
_ROLE_SHAPE_AI_BUILDER = (
    "ai engineer",
    "machine learning engineer",
    "ml engineer",
    "research engineer",
    "mlops",
    "llmops",
)
_ROLE_SHAPE_PLATFORM_BUILDER = (
    "software engineer",
    "platform engineer",
    "infrastructure engineer",
    "systems engineer",
)
_ROLE_SHAPE_PLATFORM_SIGNALS = (
    "agentic",
    "llm",
    "genai",
    "platform",
    "orchestration",
    "inference",
    "evaluation",
    "observability",
    "reliability",
    "deployment",
    "harness",
    "tooling",
)
_SOFTWARE_TITLE_AI_SIGNALS = (
    "ai",
    "machine learning",
    "ml",
    "agentic",
    "llm",
    "genai",
    "inference",
    "evaluation",
)
_REMOTE_GEO_RESTRICTIONS = (
    "emea",
    "apac",
    "europe",
    "european union",
    "east coast",
    "west coast",
    "united states",
    "u.s.",
    "us-only",
    "us only",
    "canada",
    "german speaking",
    "germany",
    "japan",
    "singapore",
    "london",
    "federal",
    "government",
    "national security",
)


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


def _job_profile(job: dict) -> dict:
    return job.get("job_profile") if isinstance(job.get("job_profile"), dict) else {}


def _engineering_builder_profile(profile: CandidateProfile) -> bool:
    blob = " ".join(profile.target_roles).lower()
    return any(term in blob for term in ("engineer", "mlops", "platform", "infrastructure", "ai"))


def _location_forms(text: str | None) -> set[str]:
    normalized = _normalize(text)
    if not normalized:
        return set()
    compact = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    forms = {normalized, compact}
    tokens = set(compact.split())
    forms.update(tokens)
    for token in list(tokens):
        forms.update(_LOCATION_ALIASES.get(token, set()))
    return {form for form in forms if form}


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
    """[-1, 1] — balance explicit YOE against title-inferred seniority."""
    text = _job_text(job)
    job_band = _normalize(_job_profile(job).get("seniority_band")) or _infer_job_seniority(job.get("title") or "")
    candidate_years = getattr(profile, "years_of_experience", None)
    yoe_match = re.search(r"\b(\d+)\s*(?:\+|plus)?\s*years\b", text)
    if yoe_match and candidate_years is not None:
        required_years = int(yoe_match.group(1))
        if candidate_years + 1 < required_years:
            return -1.0
        if candidate_years < required_years:
            return -0.35

    desired_band = profile.seniority_band.lower()
    if candidate_years is not None:
        if candidate_years <= 2:
            desired_band = "junior"
        elif candidate_years <= 5:
            desired_band = "mid"
        elif candidate_years <= 9:
            desired_band = "senior"
        else:
            desired_band = "principal"

    if job_band == desired_band:
        return 1.0
    if desired_band == "senior" and job_band == "mid":
        return 0.35
    if desired_band == "senior" and job_band == "principal":
        return -0.7
    if desired_band == "mid" and job_band == "senior":
        return -0.35
    if desired_band in {"senior", "principal"} and job_band == "junior":
        return -0.8
    if job_band == "mid":
        return 0.0
    return -0.5


def location_match(job: dict, profile: CandidateProfile) -> float:
    """[0, 1] — exact preferred city > unrestricted remote > weak/unknown."""
    job_profile = _job_profile(job)
    job_loc = str(job_profile.get("location_normalized") or job.get("location", ""))
    job_forms = _location_forms(job_loc)
    profile_locs = [_normalize(loc) for loc in profile.preferred_locations]
    profile_forms = [_location_forms(loc) for loc in profile_locs]
    combined = _normalize(f"{job_loc} {job.get('title', '')} {job.get('description', '')}")
    wants_remote = any(loc == "remote" for loc in profile_locs)
    work_mode = _normalize(job_profile.get("work_mode"))

    is_remote = "remote" in combined or work_mode == "remote"
    has_geo_restriction = any(term in combined for term in _REMOTE_GEO_RESTRICTIONS)
    if is_remote:
        if has_geo_restriction:
            return 0.0
        return 1.0 if wants_remote else 0.45

    if any(job_forms.intersection(forms) for forms in profile_forms):
        return 1.0

    if work_mode == "hybrid" and any(job_forms.intersection(forms) for forms in profile_forms):
        return 0.9

    normalized_job_loc = _normalize(job_loc)
    if any(loc and (loc in normalized_job_loc or normalized_job_loc in loc) for loc in profile_locs):
        return 1.0
    return 0.0


def role_shape_match(job: dict, profile: CandidateProfile) -> float:
    """[0, 1] — does the role behave like the job the candidate would actually take?"""
    if not _engineering_builder_profile(profile):
        return 0.5

    title = _normalize(job.get("title"))
    text = _job_text(job)
    if any(term in title for term in _ROLE_SHAPE_HARD_NEGATIVES):
        return 0.0
    if any(term in title for term in _ROLE_SHAPE_ARCHITECT):
        return 0.1
    if any(term in title for term in _ROLE_SHAPE_ADJACENT):
        return 0.45 if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS) else 0.25
    if any(term in title for term in _ROLE_SHAPE_AI_BUILDER):
        return 1.0 if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS) else 0.72
    if "software engineer" in title:
        if any(term in title for term in _SOFTWARE_TITLE_AI_SIGNALS):
            return 0.82 if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS) else 0.6
        if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS):
            return 0.35
        return 0.28
    if any(term in title for term in _ROLE_SHAPE_PLATFORM_BUILDER):
        return 0.82 if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS) else 0.55
    if any(term in text for term in _ROLE_SHAPE_PLATFORM_SIGNALS):
        return 0.55
    return 0.2


def recency_score(job: dict, profile: CandidateProfile) -> float:
    """Recency of job posting normalized to [0, 1]."""
    from domain.additive_scoring import recency_score_0_100

    posted = parse_datetime(job.get("date_posted"))
    if posted is not None:
        return recency_score_0_100(posted) / 100.0

    ingested = parse_datetime(job.get("ingested_at"))
    if ingested is None:
        return 0.25 if is_direct_source(job.get("site")) else 0.12

    now = datetime.now(ingested.tzinfo or timezone.utc)
    age_days = max(0.0, (now - ingested).total_seconds() / 86400)
    if age_days <= 1:
        return 0.88 if is_direct_source(job.get("site")) else 0.64
    if age_days <= 3:
        return 0.78 if is_direct_source(job.get("site")) else 0.52
    if age_days <= 7:
        return 0.62 if is_direct_source(job.get("site")) else 0.4
    if age_days <= 14:
        return 0.45 if is_direct_source(job.get("site")) else 0.28
    return 0.2 if is_direct_source(job.get("site")) else 0.1


def company_tier_score(job: dict, profile: CandidateProfile) -> float:
    """Company tier lookup via CompanyScorer, normalized to [0, 1].

    Uses the same CompanyScorer(cfg).classify() path as V2, reading tier lists
    from config/base.yaml. The scorer instance is cached on profile.company_tier_map
    as a pre-built {normalized_name: tier} dict to avoid reloading config per job.
    Falls back to _DEFAULT_COMPANY_SCORE (0.40) for unknown companies.
    """
    company = job.get("company") or ""
    if not company:
        return _DEFAULT_COMPANY_SCORE

    # profile.company_tier_map holds pre-classified tiers: company_name -> tier
    # Built once in extraction.py via CompanyScorer
    if profile.company_tier_map:
        from domain.company import _norm
        tier = profile.company_tier_map.get(_norm(company), "default")
    else:
        tier = "default"

    base_score = _COMPANY_TIER_SCORES.get(tier, _DEFAULT_COMPANY_SCORE)
    preferred_tiers = {str(t).strip().lower() for t in getattr(profile, "preferred_company_tiers", []) if str(t).strip()}
    if not preferred_tiers:
        return base_score

    strength = max(0.0, min(float(getattr(profile, "company_preference_strength", 1.0) or 1.0), 2.0))
    if tier in preferred_tiers:
        if tier in {"tier_ss", "tier_s"}:
            return min(1.0, base_score + 0.03 * strength)
        if tier == "tier_a":
            return min(1.0, base_score + 0.12 * strength)
        return min(1.0, base_score + 0.06 * strength)

    if tier in {"default", "", "tier_b", "tier_c", "tier_d"}:
        return max(0.0, base_score * (1.0 - 0.12 * strength))
    return base_score


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


def source_quality(job: dict, profile: CandidateProfile) -> float:
    return source_quality_score(job.get("site"))


def ingest_freshness(job: dict, profile: CandidateProfile) -> float:
    ingested = parse_datetime(job.get("ingested_at"))
    if ingested is None:
        return 0.2

    now = datetime.now(ingested.tzinfo or timezone.utc)
    age_days = max(0.0, (now - ingested).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days <= 3:
        return 0.9
    if age_days <= 7:
        return 0.75
    if age_days <= 14:
        return 0.55
    if age_days <= 30:
        return 0.35
    return 0.15


def compute_features(job: dict, profile: CandidateProfile) -> dict[str, float]:
    """Compute all scoring features for a (job, profile) pair."""
    return {
        "title_similarity": title_similarity(job, profile),
        "skill_overlap": skill_overlap(job, profile),
        "role_family_match": role_family_match(job, profile),
        "description_role_family_terms": description_role_family_terms(job, profile),
        "must_have_hits": must_have_hits(job, profile),
        "negative_hits": negative_hits(job, profile),
        "role_shape_match": role_shape_match(job, profile),
        "seniority_match": seniority_match(job, profile),
        "location_match": location_match(job, profile),
        "recency_score": recency_score(job, profile),
        "company_tier_score": company_tier_score(job, profile),
        "semantic_similarity": semantic_similarity(job, profile),
        "description_quality": description_quality(job, profile),
        "source_quality": source_quality(job, profile),
        "ingest_freshness": ingest_freshness(job, profile),
    }
