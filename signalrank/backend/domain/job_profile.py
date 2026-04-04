from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from domain.artifact_versions import (
    JOB_PROFILE_VERSION,
    SCHEMA_VERSION,
    job_profile_cache_key,
    stable_digest,
)
from domain.description_quality import description_quality_multiplier
from domain.role_clusters import infer_clusters_from_job_text
from domain.skills import extract_skills_from_texts


_ROLE_FAMILY_MAP = {
    "sap_erp": "SAP / ERP",
    "ai_ml": "AI / ML",
    "backend": "Backend / Product Engineering",
    "infra": "Platform / Infrastructure",
    "product_eng": "QA / Product Engineering",
}


def _dedupe(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _compact_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def _normalize_location(location: str | None, work_mode: str) -> str:
    loc = _compact_text(location)
    if not loc:
        return "Remote" if work_mode == "remote" else ""
    lowered = loc.lower()
    if work_mode == "remote" and "remote" not in lowered:
        return "Remote"
    if work_mode == "hybrid" and "hybrid" not in lowered:
        return f"{loc} (Hybrid)"
    return loc


def _work_mode(location: str | None, title: str, description: str) -> str:
    text = f"{location or ''} {title or ''} {description or ''}".lower()
    if any(term in text for term in ("remote", "work from home", "wfh", "fully distributed")):
        return "remote"
    if any(term in text for term in ("hybrid", "2 days", "3 days", "days in office")):
        return "hybrid"
    if location:
        return "onsite"
    return "unknown"


def _seniority_band(title: str, description: str) -> str:
    text = f"{title or ''} {description or ''}".lower()
    if any(term in text for term in ("principal", "distinguished", "architect", "head of")):
        return "principal"
    if any(term in text for term in ("staff", "lead", "manager", "director", "vp", "vice president")):
        return "senior"
    if any(term in text for term in ("senior", "sr.", "sr ")):
        return "senior"
    if any(term in text for term in ("junior", "entry", "associate", "intern")):
        return "junior"
    yoe_match = re.search(r"\b(\d+)\s*(?:-|\sto\s)\s*(\d+)\s*years\b", text)
    if yoe_match:
        high = int(yoe_match.group(2))
        if high <= 2:
            return "junior"
        if high <= 5:
            return "mid"
        if high <= 9:
            return "senior"
    return "mid"


def _family_from_clusters(clusters: Iterable[str]) -> str:
    for cluster in clusters:
        if cluster in _ROLE_FAMILY_MAP:
            return _ROLE_FAMILY_MAP[cluster]
    return "General"


def _infer_domain(title: str, description: str, clusters: Iterable[str]) -> str:
    family = _family_from_clusters(clusters)
    if family != "General":
        return family
    text = f"{title or ''} {description or ''}".lower()
    if any(term in text for term in ("sap", "s/4hana", "otc", "order to cash", "erp")):
        return "SAP / ERP"
    if any(term in text for term in ("machine learning", "llm", "genai", "mlops", "data scientist")):
        return "AI / ML"
    if any(term in text for term in ("backend", "full stack", "api", "integrations")):
        return "Backend / Product Engineering"
    if any(term in text for term in ("platform", "devops", "sre", "infrastructure", "cloud")):
        return "Platform / Infrastructure"
    if any(term in text for term in ("qa", "test", "sdet", "automation")):
        return "QA / Product Engineering"
    return "General"


def _required_constraints(description: str) -> list[str]:
    text = (description or "").lower()
    constraints: list[str] = []
    patterns = [
        (r"\bvisa sponsorship\b", "visa sponsorship"),
        (r"\bsecurity clearance\b", "security clearance"),
        (r"\b(us|u\.s\.) only\b", "US-only"),
        (r"\bindia only\b", "India-only"),
        (r"\b(on[- ]site|onsite|in office)\b", "onsite"),
        (r"\bhybrid\b", "hybrid"),
        (r"\btravel\b", "travel requirement"),
        (r"\bcontract\b", "contract"),
        (r"\bpart[- ]time\b", "part-time"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            constraints.append(label)

    yoe = re.search(r"\b(\d+)\s*[-to]+\s*(\d+)\s*years\b", text)
    if yoe:
        constraints.append(f"{yoe.group(0)} experience")
    else:
        plus = re.search(r"\b(\d+)\+?\s*years\b", text)
        if plus:
            constraints.append(f"{plus.group(0)} experience")
    return _dedupe(constraints)


def _red_flags(description: str, quality: float) -> list[str]:
    text = (description or "").lower()
    flags: list[str] = []
    if not text.strip():
        flags.append("empty_description")
    if len(text) < 180:
        flags.append("very_short_description")
    if "contract" in text or "part-time" in text or "part time" in text:
        flags.append("contract_or_part_time")
    if quality < 0.8:
        flags.append("low_description_quality")
    boilerplate_hits = sum(
        1 for phrase in ("fast paced environment", "dynamic environment", "cross functional teams", "stakeholders")
        if phrase in text
    )
    if boilerplate_hits >= 2:
        flags.append("boilerplate_heavy")
    return _dedupe(flags)


def _section_excerpt(description: str, markers: Iterable[str]) -> str:
    text = description or ""
    lower = text.lower()
    positions = [lower.find(marker) for marker in markers if marker in lower]
    if not positions:
        return ""
    idx = min(positions)
    return text[idx: idx + 500]


def _evidence_snippets(*snippets: tuple[str, str | None]) -> list[dict]:
    evidence: list[dict] = []
    for source, text in snippets:
        if not text:
            continue
        cleaned = str(text).strip()
        if cleaned:
            evidence.append({"source": source, "text": cleaned[:240]})
    return evidence


def build_job_profile(
    *,
    title: str | None,
    company: str | None = None,
    description: str | None = None,
    location: str | None = None,
    site: str | None = None,
    date_posted: Any = None,
    role_clusters: Iterable[str] | None = None,
    cfg: dict | None = None,
) -> dict:
    title_text = _compact_text(title)
    description_text = _compact_text(description)
    location_text = _compact_text(location)

    clusters = _dedupe(role_clusters)
    if not clusters or clusters == ["general"]:
        clusters = sorted(infer_clusters_from_job_text(title_text or None, description_text or None))

    required_skills = _dedupe(extract_skills_from_texts([f"{title_text} {description_text}"], cfg or {})[0])
    preferred_section = _section_excerpt(
        description_text,
        ("preferred", "nice to have", "bonus", "plus", "good to have"),
    )
    preferred_skills = _dedupe(extract_skills_from_texts([preferred_section], cfg or {})[0])

    work_mode = _work_mode(location_text or None, title_text, description_text)
    normalized_location = _normalize_location(location_text or None, work_mode)
    quality = description_quality_multiplier(description_text)
    family = _infer_domain(title_text, description_text, clusters)
    cluster_family = _family_from_clusters(clusters)
    role_family = cluster_family if cluster_family != "General" else family
    role_titles = _dedupe([
        title_text,
        re.sub(r"\s+", " ", re.sub(r"(?i)\b(senior|sr\.?|junior|jr\.?|lead|principal|staff)\b", "", title_text)).strip(),
        role_family,
    ])

    profile_payload = {
        "role_family": role_family,
        "role_titles_normalized": role_titles[:6],
        "domain": family,
        "seniority_band": _seniority_band(title_text, description_text),
        "required_skills": required_skills[:20],
        "preferred_skills": preferred_skills[:20],
        "work_mode": work_mode,
        "location_normalized": normalized_location,
        "must_have_constraints": _required_constraints(description_text)[:10],
        "red_flags": _red_flags(description_text, quality)[:10],
        "description_quality": quality,
    }
    job_fingerprint = stable_digest(
        {
            "title": title_text,
            "company": _compact_text(company),
            "description": description_text,
            "location": location_text,
            "site": _compact_text(site),
            "date_posted": str(date_posted or ""),
            "role_clusters": clusters,
            "profile_payload": profile_payload,
            "schema_version": SCHEMA_VERSION,
            "artifact_version": JOB_PROFILE_VERSION,
        }
    )

    return {
        "artifact_version": JOB_PROFILE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "job_fingerprint": job_fingerprint,
        "job_cache_key": job_profile_cache_key(
            job_fingerprint=job_fingerprint,
            profile_version=JOB_PROFILE_VERSION,
        ),
        **profile_payload,
        "evidence_snippets": _evidence_snippets(
            ("title", title_text),
            ("location", normalized_location or location_text),
            ("description", description_text[:240] if description_text else None),
            ("preferred_section", preferred_section[:240] if preferred_section else None),
        ),
    }
