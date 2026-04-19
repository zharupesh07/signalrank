from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from domain.company import CompanyScorer, _norm

DEFAULT_QUERY_TERMS = [
    "Agent Engineer",
    "Agentic AI Engineer",
    "GenAI Engineer",
    "LLM Engineer",
    "LLMOps Engineer",
    "MLOps Engineer",
    "ML Platform Engineer",
    "Machine Learning Engineer",
]

DEFAULT_LOCATIONS = [
    "Remote",
    "Pune",
    "Bangalore",
    "Gurgaon",
    "Mumbai",
    "Delhi",
    "Noida",
    "Hyderabad",
]

ROLE_BUCKET_POINTS = {
    "agentic": 45,
    "genai": 37,
    "mlops_llmops": 30,
    "ml_engineer": 22,
}

LOCATION_BUCKET_POINTS = {
    "top": 25,
    "preferred": 20,
    "acceptable": 13,
}

YOE_MATCH_POINTS = {
    "ideal": 15,
    "acceptable": 12,
    "unknown": 8,
}

COMPANY_TIER_POINTS = {
    "tier_ss": 10,
    "tier_s": 8,
    "tier_a": 6,
    "tier_b": 4,
    "default": 2,
    "tier_c": 1,
    "tier_d": 0,
}

TIER_SORT_ORDER = {
    "tier_ss": 0,
    "tier_s": 1,
    "tier_a": 2,
    "tier_b": 3,
    "tier_c": 4,
    "tier_d": 5,
    "default": 6,
}

_REMOTE_TERMS = (
    "remote",
    "work from home",
    "work-from-home",
    "work from anywhere",
    "anywhere",
    "distributed",
)
_NON_INDIA_REMOTE_TERMS = (
    "remote usa",
    "remote-us",
    "remote us",
    "us only",
    "united states only",
    "u.s. only",
    "north america",
    "canada only",
    "remote canada",
    "europe only",
    "remote europe",
    "emea",
    "apac excluding india",
    "latam",
    "uk only",
    "remote uk",
    "germany only",
    "remote germany",
    "ireland only",
    "remote ireland",
    "singapore only",
    "remote singapore",
    "remote sweden",
    "remote denmark",
    "remote finland",
)
_NON_INDIA_LOCATION_TERMS = (
    "us-",
    "usa",
    "united states",
    "u.s.",
    "new york",
    "san francisco",
    "seattle",
    "california",
    "washington state",
    "canada",
    "europe",
    "emea",
    "latam",
    "ireland",
    "uk",
    "united kingdom",
    "germany",
    "sweden",
    "stockholm",
    "denmark",
    "copenhagen",
    "finland",
    "helsinki",
    "france",
    "spain",
    "portugal",
    "netherlands",
    "poland",
    "singapore",
    "australia",
    "japan",
    "uae",
    "dubai",
)
_TITLE_HARD_REJECTS = (
    "account executive",
    "account manager",
    "product lead",
    "marketing lead",
    "manager",
    "director",
    "head",
    "vice president",
    "vp ",
    "consultant",
    "support",
    "solution engineer",
    "solutions engineer",
    "customer success",
    "sales",
    "sales engineer",
    "pre-sales",
    "presales",
    "qa",
    "quality assurance",
    "sdet",
    "process",
    "cad",
    "erp",
    "frontend",
    "front end",
    "product engineer",
    "recruiter",
    "talent acquisition",
)
_ROLE_NEGATIVES = (
    "data analyst",
    "business analyst",
    "sap",
    "oracle ebs",
    "servicenow admin",
    "desktop support",
    "technical support",
    "full stack",
    "front end",
    "frontend",
)
_AGENTIC_TERMS = (
    "agentforce",
    "agentic",
    "ai agent",
    "ai agents",
    "agent platform",
    "agent systems",
    "multi-agent",
    "multi agent",
    "agent orchestration",
    "agent framework",
    "autonomous agent",
)
_GENAI_TERMS = (
    "genai",
    "generative ai",
    "llm",
    "large language model",
    "rag",
    "retrieval augmented",
    "prompt engineer",
    "foundation model",
)
_MLOPS_TERMS = (
    "mlops",
    "llmops",
    "ml platform",
    "machine learning platform",
    "ai platform",
    "model serving",
    "model deployment",
    "inference platform",
    "feature store",
    "ml infrastructure",
)
_ML_ENGINEER_TERMS = (
    "machine learning engineer",
    "applied machine learning engineer",
    "ml engineer",
)
_ENGINEERING_IC_TITLE_TERMS = (
    "engineer",
    "engineering",
    "developer",
    "devops",
    "mlops",
    "sre",
    "platform",
    "member of technical staff",
    "mts",
    "amts",
)

_TITLE_TARGET_TERMS = (
    "agent",
    "agentic",
    "genai",
    "generative ai",
    "llm",
    "rag",
    "ai/ml",
    "ai ml",
    "machine learning",
    "ml ",
    " ml",
    "mlops",
    "llmops",
    "ai platform",
    "ml platform",
    "artificial intelligence",
)

_CITY_BUCKETS = {
    "top": (
        "pune",
    ),
    "preferred": (
        "bangalore",
        "bengaluru",
        "karnataka",
        "ka, in",
        "ka in",
    ),
    "acceptable": (
        "gurgaon",
        "gurugram",
        "mumbai",
        "delhi",
        "new delhi",
        "noida",
        "hyderabad",
        "maharashtra",
        "mh, in",
        "mh in",
        "telangana",
        "ts, in",
        "ts in",
        "ncr",
    ),
}


@dataclass(frozen=True)
class RankedJob:
    company: str
    company_tier: str
    role_bucket: str
    role_fit_band: str
    title: str
    location: str
    location_bucket: str
    remote_policy_match: str
    yoe_match_band: str
    site: str
    job_url: str
    score: float
    freshness_points: int
    company_points: int
    role_points: int
    location_points: int
    yoe_points: int
    location_compensation: int


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clean_company_value(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _normalize(text) in {"", "nan", "none", "null"}:
        return ""
    return text


def _infer_company_name(job: dict[str, Any]) -> str:
    company = _clean_company_value(job.get("company"))
    if company:
        return company

    text = _normalize(
        " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("description") or ""),
                str(job.get("job_url") or ""),
            ]
        )
    )

    if "cognite" in text:
        return "Cognite"

    email_match = re.search(r"\b([a-z0-9._%+-]+)@([a-z0-9.-]+)\b", str(job.get("description") or ""), re.IGNORECASE)
    if email_match:
        domain = email_match.group(2).split(".")[0]
        slug = re.sub(r"[^a-z0-9]+", " ", domain, flags=re.IGNORECASE).strip()
        if slug:
            return " ".join(part.capitalize() for part in slug.split())

    brand_match = re.search(
        r"^([A-Z][A-Za-z0-9&.,'-]*(?:\s+[A-Z][A-Za-z0-9&.,'-]*){0,3})\s+(?:is|are|operates|builds|seeks|seeking|looking|works|thrives)\b",
        str(job.get("description") or ""),
    )
    if brand_match:
        inferred = brand_match.group(1).strip()
        if inferred and _normalize(inferred) not in {"we", "this role", "role summary"}:
            return inferred

    return "Unattributed Employer"


def canonical_company_name(name: str, company_scorer: CompanyScorer) -> str:
    normalized = _norm(name)
    canonical = company_scorer.aliases.get(normalized, normalized)
    return canonical


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _contains_any_phrase(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, term) for term in terms)


def _contains_location_marker(text: str, marker: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(marker) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _contains_us_marker(text: str) -> bool:
    return re.search(r"(?<![a-z0-9])(us|usa|u\.s\.)(?![a-z0-9])", text) is not None


def _job_text(job: dict[str, Any]) -> str:
    return _normalize(
        " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("company") or ""),
                str(job.get("location") or ""),
                str(job.get("description") or ""),
            ]
        )
    )


def _location_text(job: dict[str, Any]) -> str:
    return _normalize(str(job.get("location") or ""))


def _location_fallback_text(job: dict[str, Any]) -> str:
    return _normalize(
        " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("description") or ""),
            ]
        )
    )


def _is_engineering_ic_title(title: str) -> bool:
    return _contains_any(title, _ENGINEERING_IC_TITLE_TERMS)


def _has_target_title_signal(title: str) -> bool:
    if _contains_any(title, _TITLE_TARGET_TERMS):
        return True
    return (
        ("ai" in title or "ml" in title or "llm" in title)
        and _is_engineering_ic_title(title)
    )


def _has_target_text_signal(text: str) -> bool:
    return any(
        _contains_any(text, terms)
        for terms in (_AGENTIC_TERMS, _GENAI_TERMS, _MLOPS_TERMS, _ML_ENGINEER_TERMS)
    )


def _extract_yoe_range(text: str) -> tuple[int | None, int | None]:
    patterns = [
        r"\b(\d+)\s*[-to]{1,3}\s*(\d+)\+?\s*(?:years|year|yrs|yr)\b",
        r"\b(\d+)\s*(?:to|-)\s*(\d+)\s*(?:years|year|yrs|yr)\b",
        r"\b(\d+)\+?\s*(?:years|year|yrs|yr)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        first = int(match.group(1))
        second = int(match.group(2)) if match.lastindex and match.lastindex >= 2 else None
        if second is None:
            return first, first
        low, high = sorted((first, second))
        return low, high
    return None, None


def classify_role_bucket(job: dict[str, Any]) -> tuple[str | None, str | None]:
    title = _normalize(job.get("title"))
    text = _job_text(job)
    if _contains_any_phrase(title, _TITLE_HARD_REJECTS):
        return None, None
    if _contains_any(text, _ROLE_NEGATIVES):
        return None, None
    if not _is_engineering_ic_title(title):
        return None, None
    title_has_target_signal = _has_target_title_signal(title)
    if not title_has_target_signal:
        return None, None

    if _contains_any(title, _AGENTIC_TERMS):
        return "agentic", "strong"
    if _contains_any(text, _AGENTIC_TERMS):
        return "agentic", "moderate"

    if _contains_any(title, _GENAI_TERMS):
        return "genai", "strong"
    if _contains_any(text, _GENAI_TERMS):
        return "genai", "moderate"

    if _contains_any(title, _MLOPS_TERMS):
        return "mlops_llmops", "strong"
    if _contains_any(text, _MLOPS_TERMS):
        return "mlops_llmops", "moderate"

    if _contains_any(title, _ML_ENGINEER_TERMS):
        return "ml_engineer", "strong"

    if "machine learning" in text and "engineer" in title:
        return "ml_engineer", "moderate"

    return None, None


def classify_location(job: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    text = _location_text(job)
    fallback_text = _location_fallback_text(job)
    remote_text = text or fallback_text
    if _contains_any(remote_text, _REMOTE_TERMS):
        if _contains_any(remote_text, _NON_INDIA_REMOTE_TERMS) or _contains_us_marker(remote_text):
            return None, None, "geo_restricted_remote"
        if text and _contains_any(text, _NON_INDIA_LOCATION_TERMS):
            return None, None, "geo_restricted_remote"
        if "india" in remote_text:
            return "top", "india_safe", None
        return "top", "global_safe", None

    if text and (_contains_any(text, _NON_INDIA_LOCATION_TERMS) or _contains_us_marker(text)):
        return None, None, "non_india_location"

    for bucket, markers in _CITY_BUCKETS.items():
        if any(_contains_location_marker(text, marker) for marker in markers):
            return bucket, "city_match", None
    return None, None, "unsupported_location"


def classify_yoe(job: dict[str, Any]) -> tuple[str | None, str | None]:
    low, high = _extract_yoe_range(_job_text(job))
    if low is None and high is None:
        return "unknown", None
    high = high if high is not None else low
    low = low if low is not None else high
    if high is not None and high < 5:
        return None, "yoe_too_low"
    if low is not None and low > 9:
        return None, "yoe_too_high"
    if low <= 7 <= high:
        return "ideal", None
    if max(low, 5) <= min(high, 9):
        return "acceptable", None
    return "acceptable", None


def compute_freshness_points(job: dict[str, Any]) -> int:
    posted = job.get("date_posted")
    if isinstance(posted, str):
        try:
            posted = datetime.fromisoformat(posted)
        except ValueError:
            posted = None
    if not isinstance(posted, datetime):
        return 2
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - posted).total_seconds() / 86400)
    if age_days <= 3:
        return 5
    if age_days <= 7:
        return 4
    if age_days <= 14:
        return 2
    return 1


def _location_compensation(company_tier: str, role_bucket: str, role_fit_band: str, location_bucket: str, yoe_band: str) -> int:
    if company_tier not in {"tier_ss", "tier_s"}:
        return 0
    if role_bucket not in {"agentic", "genai", "mlops_llmops"}:
        return 0
    if role_fit_band != "strong":
        return 0
    if yoe_band not in {"ideal", "acceptable"}:
        return 0
    if location_bucket != "acceptable":
        return 0
    return 5


def rank_profile_fresh_jobs(
    jobs: list[dict[str, Any]],
    *,
    company_scorer: CompanyScorer,
    allowed_companies: list[str] | None = None,
) -> tuple[list[RankedJob], Counter[str]]:
    accepted: list[RankedJob] = []
    rejections: Counter[str] = Counter()
    allowed_company_keys = {
        canonical_company_name(company, company_scorer)
        for company in (allowed_companies or [])
        if str(company).strip()
    }

    for job in jobs:
        company = _infer_company_name(job)
        title = str(job.get("title") or "").strip()
        url = str(job.get("job_url") or "").strip()
        if not company or not title or not url:
            rejections["missing_core_fields"] += 1
            continue

        company_key = canonical_company_name(company, company_scorer)
        if allowed_company_keys and company_key not in allowed_company_keys:
            rejections["company_filtered_out"] += 1
            continue

        role_bucket, role_fit_band = classify_role_bucket(job)
        if role_bucket is None or role_fit_band is None:
            rejections["role_mismatch"] += 1
            continue

        location_bucket, remote_policy_match, location_reason = classify_location(job)
        if location_bucket is None or remote_policy_match is None:
            rejections[location_reason or "location_mismatch"] += 1
            continue

        yoe_match_band, yoe_reason = classify_yoe(job)
        if yoe_match_band is None:
            rejections[yoe_reason or "yoe_mismatch"] += 1
            continue

        company_tier = company_scorer.classify(company)
        role_points = ROLE_BUCKET_POINTS[role_bucket]
        location_points = LOCATION_BUCKET_POINTS[location_bucket]
        yoe_points = YOE_MATCH_POINTS[yoe_match_band]
        company_points = COMPANY_TIER_POINTS.get(company_tier, COMPANY_TIER_POINTS["default"])
        freshness_points = compute_freshness_points(job)
        location_compensation = _location_compensation(
            company_tier,
            role_bucket,
            role_fit_band,
            location_bucket,
            yoe_match_band,
        )

        score = role_points + location_points + yoe_points + freshness_points + company_points + location_compensation
        accepted.append(
            RankedJob(
                company=company,
                company_tier=company_tier,
                role_bucket=role_bucket,
                role_fit_band=role_fit_band,
                title=title,
                location=str(job.get("location") or "").strip(),
                location_bucket=location_bucket,
                remote_policy_match=remote_policy_match,
                yoe_match_band=yoe_match_band,
                site=str(job.get("site") or "").strip(),
                job_url=url,
                score=round(float(score), 4),
                freshness_points=freshness_points,
                company_points=company_points,
                role_points=role_points,
                location_points=location_points,
                yoe_points=yoe_points,
                location_compensation=location_compensation,
            )
        )

    accepted.sort(
        key=lambda item: (
            -item.score,
            TIER_SORT_ORDER.get(item.company_tier, TIER_SORT_ORDER["default"]),
            item.company.lower(),
            item.title.lower(),
        )
    )
    return accepted, rejections


def select_top_companies(jobs: list[RankedJob], *, limit: int = 100) -> list[dict[str, Any]]:
    company_rows: list[dict[str, Any]] = []
    counts = Counter(job.company for job in jobs)
    seen: set[str] = set()

    for job in jobs:
        key = job.company.lower()
        if key in seen:
            continue
        seen.add(key)
        company_rows.append(
            {
                "company_tier": job.company_tier,
                "company": job.company,
                "role_bucket": job.role_bucket,
                "best_job_title": job.title,
                "best_job_location": job.location,
                "location_bucket": job.location_bucket,
                "remote_policy_match": job.remote_policy_match,
                "yoe_match_band": job.yoe_match_band,
                "site": job.site,
                "best_job_url": job.job_url,
                "score": job.score,
                "jobs_considered_for_company": counts[job.company],
            }
        )
        if len(company_rows) >= limit:
            break

    for idx, row in enumerate(company_rows, start=1):
        row["company_rank"] = idx
    return company_rows


def summarize_profile_fresh_run(
    *,
    scraped_jobs: int,
    ranked_jobs: list[RankedJob],
    company_rows: list[dict[str, Any]],
    rejection_counts: Counter[str],
    sources: list[str],
    queries: list[str],
) -> dict[str, Any]:
    return {
        "scraped_jobs": scraped_jobs,
        "jobs_scored": len(ranked_jobs),
        "companies_exported": len(company_rows),
        "sources": sources,
        "queries": queries,
        "rejection_counts": dict(sorted(rejection_counts.items())),
    }
