from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from domain.artifact_versions import (
    CANDIDATE_PROFILE_VERSION,
    SCHEMA_VERSION,
    candidate_profile_cache_key,
    stable_digest,
)
from domain.intent_matching import PROFILE_INTENT_KEY, build_profile_intent
from domain.role_clusters import infer_clusters_from_job_text, roles_to_clusters
from domain.skills import SkillCanonicalizer, extract_skills_from_texts
from llm.resume_parser import ResumeParseResult


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


def _extract_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        for key in ("title", "label", "name", "term", "role"):
            item = str(value.get(key, "") or "").strip()
            if item:
                return [item]
        return []
    if isinstance(value, Iterable):
        collected: list[str] = []
        for item in value:
            if isinstance(item, dict):
                for key in ("title", "label", "name", "term", "role"):
                    text = str(item.get(key, "") or "").strip()
                    if text:
                        collected.append(text)
                        break
            else:
                text = str(item or "").strip()
                if text:
                    collected.append(text)
        return collected
    return [str(value).strip()]


def _title_band_from_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(
        term in lowered
        for term in ("principal", "distinguished", "architect", "head of")
    ):
        return "principal"
    if any(term in lowered for term in ("staff", "lead", "manager", "director")):
        return "senior"
    if any(term in lowered for term in ("senior", "sr.", "sr ", "ii", "iii")):
        return "senior"
    if any(
        term in lowered
        for term in ("junior", "entry", "intern", "associate", "assistant")
    ):
        return "junior"
    return "mid"


def _band_from_years(years: int | None) -> str | None:
    if years is None:
        return None
    if years <= 2:
        return "junior"
    if years <= 5:
        return "mid"
    if years <= 9:
        return "senior"
    if years <= 13:
        return "staff"
    return "principal"


def _infer_seniority_band(*, years: int | None, text: str, roles: Iterable[str]) -> str:
    band = _band_from_years(years)
    if band:
        return band
    role_band = _title_band_from_text(" ".join(roles))
    if role_band != "mid":
        return role_band
    return _title_band_from_text(text)


def _infer_work_modes(text: str, preferred_locations: list[str]) -> list[str]:
    lowered = (text or "").lower()
    locations = " ".join(preferred_locations).lower()
    modes: list[str] = []

    if any(
        term in lowered or term in locations
        for term in ("remote", "wfh", "work from home", "fully distributed")
    ):
        modes.append("remote")
    if any(
        term in lowered or term in locations
        for term in ("hybrid", "2 days", "3 days", "days per week")
    ):
        modes.append("hybrid")
    if any(
        term in lowered or term in locations
        for term in ("onsite", "on-site", "in office", "office")
    ):
        modes.append("onsite")

    return _dedupe(modes) or ["any"]


def _infer_domain(
    archetypes: list[str], roles: list[str], resume_text: str
) -> list[str]:
    text = " ".join([resume_text, " ".join(archetypes), " ".join(roles)]).lower()
    domains: list[str] = []
    if any(term in text for term in ("sap", "s/4hana", "order to cash", "otc", "erp")):
        domains.append("Enterprise Apps")
    if any(
        term in text
        for term in ("machine learning", "llm", "genai", "mlops", "data science")
    ):
        domains.append("AI / ML")
    if any(
        term in text
        for term in ("kubernetes", "terraform", "devops", "platform", "sre")
    ):
        domains.append("Platform / Infrastructure")
    if any(term in text for term in ("backend", "full stack", "api", "integrations")):
        domains.append("Backend / Product Engineering")
    if any(term in text for term in ("qa", "test", "sdet", "automation")):
        domains.append("QA / Automation")
    return _dedupe(domains) or ["General"]


def _role_family_from_text(title: str, clusters: Iterable[str] | None = None) -> str:
    cluster_set = set(clusters or [])
    if "sap_erp" in cluster_set:
        return "SAP / ERP"
    if "ai_ml" in cluster_set:
        return "AI / ML"
    if "infra" in cluster_set:
        return "Platform / Infrastructure"
    if "backend" in cluster_set:
        return "Backend / Product Engineering"
    if "product_eng" in cluster_set:
        return "QA / Product Engineering"

    lowered = (title or "").lower()
    if any(term in lowered for term in ("sap", "s/4hana", "order to cash", "otc")):
        return "SAP / ERP"
    if any(
        term in lowered
        for term in ("machine learning", "ml", "llm", "genai", "data scientist")
    ):
        return "AI / ML"
    if any(
        term in lowered
        for term in ("platform", "devops", "sre", "infrastructure", "cloud")
    ):
        return "Platform / Infrastructure"
    if any(
        term in lowered
        for term in ("backend", "full stack", "software engineer", "api")
    ):
        return "Backend / Product Engineering"
    if any(term in lowered for term in ("qa", "test", "sdet", "automation")):
        return "QA / Product Engineering"
    return "General"


def _evidence_snippets(*snippets: tuple[str, str | None]) -> list[dict]:
    evidence: list[dict] = []
    for source, text in snippets:
        if not text:
            continue
        cleaned = str(text).strip()
        if cleaned:
            evidence.append({"source": source, "text": cleaned[:240]})
    return evidence


def _candidate_role_lists(
    *,
    parsed: ResumeParseResult,
    profile_roles: list[str],
    resume_text: str,
    career_intent: dict,
) -> tuple[list[str], list[str], list[str], list[str]]:
    parsed_roles = _dedupe(
        _extract_strings(parsed.target_roles)
        or _extract_strings(parsed.suggested_roles)
    )
    profile_roles = _dedupe(profile_roles)
    primary = _dedupe(parsed_roles + profile_roles)[:6]

    adjacent = _dedupe(
        _extract_strings(parsed.recent_titles)
        + _extract_strings((career_intent.get("query_plan") or {}).get("title_queries"))
    )
    if not adjacent:
        adjacent = _dedupe(_extract_strings(parsed.recent_titles))

    negative = _dedupe(
        _extract_strings(parsed.negative_targets)
        + _extract_strings(parsed.suggested_exclusions)
        + _extract_strings((career_intent.get("negative_targets") or []))
        + _extract_strings(
            (career_intent.get("work_preferences") or {}).get("exclude_roles")
        )
    )

    role_pool = primary + adjacent
    cluster_source = " ".join(role_pool or [resume_text])
    clusters = sorted(
        roles_to_clusters(role_pool or _extract_strings(parsed.recent_titles))
    )
    if not clusters or clusters == ["general"]:
        clusters = sorted(infer_clusters_from_job_text(cluster_source, resume_text))

    return primary, adjacent[:6], negative[:10], clusters


def _skills_for_profile(
    *,
    parsed: ResumeParseResult,
    profile_skills: list[str],
    resume_text: str,
    cfg: dict,
    career_intent: dict,
) -> tuple[list[str], list[str]]:
    canonicalizer = SkillCanonicalizer(cfg)
    raw_skills = _dedupe(
        _extract_strings(parsed.skills) + _extract_strings(profile_skills)
    )
    if not raw_skills and resume_text:
        raw_skills = _dedupe(extract_skills_from_texts([resume_text], cfg)[0])
    canonical = sorted(canonicalizer.canonicalize(raw_skills))

    query_plan = (
        career_intent.get("query_plan")
        if isinstance(career_intent.get("query_plan"), dict)
        else {}
    )
    good_to_have = _dedupe(
        _extract_strings(query_plan.get("skill_queries"))
        + _extract_strings(query_plan.get("domain_queries"))
    )
    good_to_have = [
        skill
        for skill in good_to_have
        if skill.lower() not in {item.lower() for item in canonical}
    ]
    return canonical[:16], good_to_have[:12]


def build_candidate_profile(
    *,
    parsed: ResumeParseResult | None = None,
    profile: object | None = None,
    resume_text: str | None = None,
    cfg: dict | None = None,
) -> dict:
    parsed = parsed or ResumeParseResult()
    cfg = cfg or {}

    profile_resume_text = str(getattr(profile, "resume_text", "") or "")
    profile_distilled_text = str(getattr(profile, "distilled_text", "") or "")
    full_resume_text = " ".join(
        part
        for part in [resume_text, profile_resume_text, profile_distilled_text]
        if part
    ).strip()

    profile_roles = _extract_strings(getattr(profile, "target_roles", None))
    profile_locations = _extract_strings(getattr(profile, "preferred_locations", None))
    profile_skills = _extract_strings(getattr(profile, "skills", None))
    profile_overrides = (
        getattr(profile, "config_overrides", None) if profile is not None else None
    )
    career_intent = {}
    if isinstance(profile_overrides, dict):
        candidate = profile_overrides.get("career_intent")
        if isinstance(candidate, dict):
            career_intent = candidate

    if not full_resume_text and isinstance(profile_overrides, dict):
        resume_editor = profile_overrides.get("resume_editor")
        if isinstance(resume_editor, dict):
            full_resume_text = " ".join(
                str(resume_editor.get(key, "") or "")
                for key in ("name", "position", "summary")
            ).strip()

    target_primary, target_adjacent, negative_roles, career_clusters = (
        _candidate_role_lists(
            parsed=parsed,
            profile_roles=profile_roles,
            resume_text=full_resume_text,
            career_intent=career_intent,
        )
    )

    locations = _dedupe(
        _extract_strings(parsed.suggested_locations)
        + profile_locations
        + _extract_strings(
            (career_intent.get("work_preferences") or {}).get("locations")
        )
    )
    if not locations and full_resume_text:
        if any(
            term in full_resume_text.lower()
            for term in ("remote", "wfh", "work from home")
        ):
            locations = ["Remote only"]

    work_modes = _infer_work_modes(
        full_resume_text,
        locations,
    )

    must_have_skills, good_to_have_skills = _skills_for_profile(
        parsed=parsed,
        profile_skills=profile_skills,
        resume_text=full_resume_text,
        cfg=cfg,
        career_intent=career_intent,
    )

    target_roles = (
        target_primary or profile_roles or _extract_strings(parsed.recent_titles)
    )
    seniority_band = _infer_seniority_band(
        years=parsed.years_of_experience or getattr(profile, "min_yoe", None),
        text=full_resume_text,
        roles=target_roles + _extract_strings(parsed.recent_titles),
    )

    domains = _infer_domain(
        career_clusters,
        target_roles,
        full_resume_text,
    )

    archetypes = _dedupe(
        [
            str(item.get("id", "")).strip()
            for item in (parsed.career_archetypes or [])
            if isinstance(item, dict)
        ]
        + _extract_strings(career_intent.get("career_archetypes"))
    )

    ambiguities = _dedupe(
        _extract_strings(parsed.ambiguities)
        + _extract_strings((career_intent.get("ambiguities") or []))
    )
    confidence_by_field = {
        "roles": 0.92 if target_primary else 0.74 if target_adjacent else 0.52,
        "skills": min(0.96, 0.42 + 0.07 * min(len(must_have_skills), 6)),
        "domains": 0.88 if domains and domains[0] != "General" else 0.52,
        "seniority": (
            0.86 if parsed.years_of_experience is not None or target_primary else 0.6
        ),
        "locations": 0.8 if locations else 0.48,
        "overall": 0.82,
    }
    confidence_by_field["overall"] = round(
        max(
            0.05,
            min(
                0.98,
                (
                    confidence_by_field["roles"] * 0.28
                    + confidence_by_field["skills"] * 0.24
                    + confidence_by_field["domains"] * 0.16
                    + confidence_by_field["seniority"] * 0.16
                    + confidence_by_field["locations"] * 0.08
                    + (0.08 if not ambiguities else 0.0)
                    - min(0.18, 0.04 * len(ambiguities))
                ),
            ),
        ),
        3,
    )

    profile_payload = {
        "target_roles_primary": target_primary[:6],
        "target_roles_adjacent": target_adjacent[:6],
        "negative_roles": negative_roles[:10],
        "domains": domains[:6],
        "seniority_band": seniority_band,
        "preferred_locations": locations[:6],
        "preferred_work_modes": work_modes[:3],
        "must_have_skills": must_have_skills,
        "good_to_have_skills": good_to_have_skills,
        "career_archetypes": archetypes[:8],
        "ambiguities": ambiguities[:10],
        "confidence_by_field": confidence_by_field,
        "schema_version": SCHEMA_VERSION,
        "artifact_version": CANDIDATE_PROFILE_VERSION,
    }
    profile_payload[PROFILE_INTENT_KEY] = build_profile_intent(
        profile_payload,
        resume_text=full_resume_text,
    )
    profile_fingerprint = stable_digest(
        {
            "resume_text": full_resume_text,
            "profile_roles": profile_roles,
            "profile_locations": profile_locations,
            "profile_skills": profile_skills,
            "profile_payload": profile_payload,
        }
    )

    return {
        "artifact_version": CANDIDATE_PROFILE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "profile_fingerprint": profile_fingerprint,
        "profile_cache_key": candidate_profile_cache_key(
            resume_fingerprint=profile_fingerprint,
            profile_version=CANDIDATE_PROFILE_VERSION,
        ),
        **profile_payload,
        "evidence_snippets": _evidence_snippets(
            ("parsed_roles", ", ".join(target_primary or target_roles[:6])),
            ("parsed_titles", ", ".join(_extract_strings(parsed.recent_titles))),
            ("parsed_skills", ", ".join(must_have_skills)),
            ("parsed_locations", ", ".join(locations)),
            ("resume_text", full_resume_text[:240] if full_resume_text else None),
        ),
        "ambiguities": ambiguities[:10],
    }
