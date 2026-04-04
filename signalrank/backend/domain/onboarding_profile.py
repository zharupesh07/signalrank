from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from domain.candidate_profile import build_candidate_profile
from domain.career_intent import build_career_intent_profile
from domain.profile_rules import infer_profile_archetypes, refine_profile_roles_for_ranking
from domain.skills import extract_skills_from_texts
from llm.resume_parser import ResumeParseResult, detect_enterprise_role_from_text


def _normalize_str_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if not item or key in seen or key in {"none", "null", "nan"}:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def infer_yoe_range(years_of_experience: int | None) -> tuple[int | None, int | None]:
    if years_of_experience is None:
        return None, None
    yoe = max(0, int(years_of_experience))
    return max(0, yoe - 2), min(30, yoe + 2)


def enterprise_locations(parsed: ResumeParseResult) -> list[str] | None:
    text = (parsed.skills or []) + (parsed.recent_titles or []) + (parsed.suggested_locations or [])
    combined = " ".join(text).lower()
    if "bangalore" in combined or "bengaluru" in combined or "hyderabad" in combined or "hydrabad" in combined:
        return ["Bangalore", "Hyderabad"]
    return None


def flatten_editor_skills(editor: dict) -> list[str]:
    skills: list[str] = []
    for group in editor.get("skills") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            text = str(item or "").strip()
            if text:
                skills.append(text)
    return _normalize_str_list(skills)


def extract_years_from_text(text: str) -> int | None:
    matches = [
        int(match)
        for match in re.findall(r"(\d{1,2})\+?\s*(?:years?|yrs?)\b", text or "", flags=re.I)
        if match
    ]
    if not matches:
        return None
    return max(matches)


def deterministic_resume_parse(resume_text: str, profile: Any | None = None) -> ResumeParseResult:
    resume_text_lower = (resume_text or "").lower()
    editor = parse_resume_editor(resume_text)
    skills = flatten_editor_skills(editor)
    if not skills and resume_text:
        cfg = {}
        skills = _normalize_str_list(extract_skills_from_texts([resume_text], cfg)[0])
    recent_titles = _normalize_str_list(
        exp.get("title")
        for exp in (editor.get("experiences") or [])[:3]
        if isinstance(exp, dict)
    )
    education = _normalize_str_list(
        edu.get("degree")
        for edu in (editor.get("education") or [])
        if isinstance(edu, dict)
    )
    locations = _normalize_str_list([editor.get("location", "")] + list(getattr(profile, "preferred_locations", None) or []))
    years = extract_years_from_text(" ".join([resume_text, editor.get("summary", "") or ""]))
    seed_signals = extract_resume_seed_signals(
        ResumeParseResult(
            skills=skills,
            years_of_experience=years,
            recent_titles=recent_titles,
            education=education,
        ),
        profile=profile,
    )
    profile_roles = _normalize_str_list([getattr(profile, "role_intent", "")] + list(getattr(profile, "target_roles", None) or []) + recent_titles)
    inferred_archetypes = infer_profile_archetypes(resume_text, profile_roles, {})
    inferred_roles = refine_profile_roles_for_ranking(profile_roles, resume_text=resume_text, archetypes=inferred_archetypes)
    archetype_role_map = {
        "sap_sd": ["SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant"],
        "ai_platform_engineer": ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"],
        "innovation_rd_engineer": ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"],
        "network_automation_engineer": ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"],
        "sap_functional": ["SAP Functional Consultant", "SAP OTC Functional Consultant", "SAP SD Consultant"],
    }
    archetype_roles: list[str] = []
    for archetype in inferred_archetypes:
        archetype_roles.extend(archetype_role_map.get(archetype, []))
    suggested_roles = infer_seed_roles({**seed_signals, "resume_text": resume_text}) or _normalize_str_list(
        [getattr(profile, "role_intent", "")] + list(getattr(profile, "target_roles", None) or []) + archetype_roles + inferred_roles + recent_titles
    )
    if not suggested_roles and inferred_archetypes:
        suggested_roles = _normalize_str_list(archetype_roles or inferred_roles or recent_titles)
    if not suggested_roles:
        if detect_enterprise_role_from_text(resume_text):
            suggested_roles = ["SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant"]
        elif any(term in resume_text_lower for term in ("ai platform", "mlops", "llmops", "internal developer platform", "platform engineer")):
            suggested_roles = ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"]
        elif any(term in resume_text_lower for term in ("innovation", "emerging technolog", "prototype", "r&d", "research engineer")):
            suggested_roles = ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"]
        elif any(term in resume_text_lower for term in ("network automation", "infrastructure automation", "cloud networking", "network engineer", "firewall", "load balancer")):
            suggested_roles = ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"]
    if detect_enterprise_role_from_text(resume_text):
        suggested_roles = _normalize_str_list(["SAP SD Consultant", *suggested_roles])
    elif any(term in resume_text_lower for term in ("ai platform", "mlops", "llmops", "internal developer platform", "platform engineer")):
        suggested_roles = _normalize_str_list(["AI Platform Engineer", *suggested_roles])
    elif any(term in resume_text_lower for term in ("innovation", "emerging technolog", "prototype", "r&d", "research engineer")):
        suggested_roles = _normalize_str_list(["Innovation Engineer", *suggested_roles])
    elif any(term in resume_text_lower for term in ("network automation", "infrastructure automation", "cloud networking", "network engineer", "firewall", "load balancer")):
        suggested_roles = _normalize_str_list(["Network Automation Engineer", *suggested_roles])
    career_archetypes = [
        {
            "id": archetype,
            "label": archetype.replace("_", " ").title(),
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": 0.92 if idx == 0 else 0.8,
            "evidence": ["Deterministic resume text classification"],
        }
        for idx, archetype in enumerate(inferred_archetypes[:4])
    ]
    target_roles = [
        {
            "title": role,
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": 0.95 if idx == 0 else 0.85,
            "evidence": ["Deterministic resume text classification"],
        }
        for idx, role in enumerate(suggested_roles[:5])
    ]
    base_parsed = ResumeParseResult(
        skills=skills,
        years_of_experience=years,
        recent_titles=recent_titles,
        education=education,
        suggested_roles=suggested_roles[:5],
        suggested_locations=locations[:3],
        career_archetypes=career_archetypes,
        target_roles=target_roles,
    )
    career_intent = build_career_intent_profile(base_parsed)
    suggested_search_queries = _normalize_str_list(
        list((career_intent.get("query_plan") or {}).get("title_queries") or [])
        + list((career_intent.get("query_plan") or {}).get("skill_queries") or [])
        + recent_titles[:2]
    )
    suggested_exclusions = _normalize_str_list(
        [str(item.get("label", "") or "") for item in career_intent.get("negative_targets", []) if isinstance(item, dict)]
        + list((career_intent.get("query_plan") or {}).get("negative_keywords") or [])
    )
    return ResumeParseResult(
        skills=skills,
        years_of_experience=years,
        recent_titles=recent_titles,
        education=education,
        suggested_roles=suggested_roles[:5],
        suggested_locations=locations[:3],
        suggested_exclusions=suggested_exclusions[:6],
        suggested_search_queries=suggested_search_queries[:5],
        career_archetypes=career_intent.get("career_archetypes") or [],
        target_roles=career_intent.get("target_roles") or [],
        domains=career_intent.get("domains") or [],
        negative_targets=career_intent.get("negative_targets") or [],
        false_friend_terms=career_intent.get("false_friend_terms") or [],
        query_plan=career_intent.get("query_plan") or {},
        ambiguities=career_intent.get("ambiguities") or [],
        follow_up_questions=career_intent.get("follow_up_questions") or [],
    )


def extract_resume_seed_signals(parsed: ResumeParseResult, profile: Any | None = None) -> dict:
    resume_text = str(getattr(profile, "resume_text", "") or "")
    skills = _normalize_str_list(parsed.skills)
    recent_titles = _normalize_str_list(parsed.recent_titles)
    suggested_roles = _normalize_str_list(
        [getattr(profile, "role_intent", "")] + list(getattr(profile, "target_roles", None) or []) + recent_titles
    )
    locations = _normalize_str_list(
        [getattr(profile, "location", "")]  # type: ignore[attr-defined]
        + list(getattr(profile, "preferred_locations", None) or [])
    )
    return {
        "skills": skills,
        "recent_titles": recent_titles,
        "suggested_roles": suggested_roles,
        "suggested_locations": locations,
        "resume_text": resume_text,
    }


def infer_seed_roles(signals: dict) -> list[str]:
    resume_text = str(signals.get("resume_text") or "").lower()
    suggested_roles = _normalize_str_list(signals.get("suggested_roles"))
    recent_titles = _normalize_str_list(signals.get("recent_titles"))
    roles = suggested_roles or recent_titles
    if not roles:
        if any(term in resume_text for term in ("sap", "s/4hana", "order to cash", "otc")):
            roles = ["SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant"]
        elif any(term in resume_text for term in ("ai platform", "mlops", "llmops", "platform engineer")):
            roles = ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"]
        elif any(term in resume_text for term in ("innovation", "emerging technolog", "r&d")):
            roles = ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"]
        elif any(term in resume_text for term in ("network automation", "infrastructure automation", "cloud network")):
            roles = ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"]
    return _normalize_str_list(roles)[:5]


def should_run_onboarding_llm(candidate_profile: dict | None, parsed: ResumeParseResult) -> bool:
    if not candidate_profile:
        return True
    if len(parsed.recent_titles or []) == 0 or len(parsed.skills or []) == 0:
        return True
    if len(candidate_profile.get("ambiguities") or []) > 0:
        return True
    confidence = candidate_profile.get("confidence_by_field", {})
    if isinstance(confidence, dict):
        try:
            return float(confidence.get("overall") or 0.0) < 0.6
        except (TypeError, ValueError):
            return True
    return True


def build_profile_patch(
    *,
    target_roles: Iterable[str] | None = None,
    preferred_locations: Iterable[str] | None = None,
    title_blocklist: Iterable[str] | None = None,
    parse_status: str | None = None,
    resume_editor: dict | None = None,
    career_intent: dict | None = None,
    profile_intent_roles: Iterable[str] | None = None,
    scraping_locations: Iterable[str] | None = None,
) -> dict:
    overrides: dict = {}
    if target_roles is not None:
        overrides.setdefault("profile_intent", {})["roles"] = _normalize_str_list(target_roles)
    if profile_intent_roles is not None:
        overrides.setdefault("profile_intent", {})["roles"] = _normalize_str_list(profile_intent_roles)
    if preferred_locations is not None:
        overrides.setdefault("scraping", {})["locations"] = _normalize_str_list(preferred_locations)
    if scraping_locations is not None:
        overrides.setdefault("scraping", {})["locations"] = _normalize_str_list(scraping_locations)
    if title_blocklist is not None:
        overrides["title_blocklist"] = _normalize_str_list(title_blocklist)
    if parse_status is not None:
        overrides.setdefault("onboarding", {})["parse_status"] = parse_status
    if resume_editor is not None:
        overrides["resume_editor"] = resume_editor
    if career_intent is not None:
        overrides["career_intent"] = career_intent
    return overrides


def merge_profile_patch(existing: dict | None, patch: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_profile_patch(merged.get(key), value)
        else:
            merged[key] = value
    return merged


def sync_career_intent_override(profile: Any) -> None:
    overrides = dict(getattr(profile, "config_overrides", None) or {})
    career_intent = dict(overrides.get("career_intent") or {})
    work_preferences = dict(career_intent.get("work_preferences") or {})
    query_plan = dict(career_intent.get("query_plan") or {})

    target_roles = _normalize_str_list(getattr(profile, "target_roles", None))
    if target_roles:
        career_intent["target_roles"] = [
            {
                "title": role,
                "priority": "primary" if idx == 0 else "secondary",
                "confidence": 0.9 if idx == 0 else 0.75,
                "evidence": ["User-confirmed target role"],
            }
            for idx, role in enumerate(target_roles)
        ]
        query_plan["title_queries"] = _normalize_str_list(query_plan.get("title_queries", []) + target_roles)

    preferred_locations = _normalize_str_list(getattr(profile, "preferred_locations", None))
    if preferred_locations:
        work_preferences["locations"] = preferred_locations

    title_blocklist = _normalize_str_list(overrides.get("title_blocklist") or [])
    if title_blocklist:
        career_intent["negative_targets"] = [
            {
                "label": label,
                "reason": "User-specified exclusion",
                "confidence": 1.0,
            }
            for label in title_blocklist
        ]
        query_plan["negative_keywords"] = title_blocklist

    career_intent["work_preferences"] = work_preferences
    career_intent["query_plan"] = query_plan
    setattr(profile, "config_overrides", merge_profile_patch(overrides, build_profile_patch(career_intent=career_intent)))


def apply_parsed_profile_updates(profile: Any, parsed: ResumeParseResult) -> str | None:
    profile.skills = parsed.skills
    career_intent = build_career_intent_profile(parsed)
    suggested_roles = _normalize_str_list(parsed.suggested_roles)
    suggested_locations = _normalize_str_list(parsed.suggested_locations)
    suggested_exclusions = _normalize_str_list(parsed.suggested_exclusions)
    explicit_target_roles = _normalize_str_list(
        role.get("title")
        for role in career_intent.get("target_roles", [])
        if isinstance(role, dict)
    )
    structured_locations = _normalize_str_list(
        ((career_intent.get("work_preferences") or {}).get("locations")) or []
    )
    structured_negatives = _normalize_str_list(
        target.get("label")
        for target in career_intent.get("negative_targets", [])
        if isinstance(target, dict)
    )
    query_plan = dict(career_intent.get("query_plan") or {})
    combined_text = " ".join((parsed.skills or []) + (parsed.recent_titles or [])).lower()
    ai_signals = 0
    if set((parsed.skills or [])).intersection({"llm", "agents", "genai", "mlops", "deep learning", "rag", "conversational ai"}):
        ai_signals += 1
    titles_text = " ".join(parsed.recent_titles or []).lower()
    if any(term in titles_text for term in {"ai", "ml", "mlops", "llm", "genai", "machine learning"}):
        ai_signals += 1
    if any(term in combined_text for term in {"ai", "ml", "mlops", "llm", "genai", "machine learning"}):
        ai_signals += 1
    accept_suggested = bool(suggested_roles) and (ai_signals >= 2 or not all(any(term in role.lower() for term in {"ai", "ml", "genai", "agent", "mlo", "machine learning"}) for role in suggested_roles))
    enterprise_role = None
    if any(term in combined_text for term in ("sap", "s/4hana", "order to cash", "otc")):
        enterprise_role = "SAP SD Consultant"
    if explicit_target_roles:
        profile.target_roles = explicit_target_roles
        profile.role_intent = explicit_target_roles[0]
    elif accept_suggested:
        profile.target_roles = suggested_roles
        profile.role_intent = suggested_roles[0]
    elif enterprise_role:
        profile.target_roles = [enterprise_role]
        profile.role_intent = enterprise_role
    elif parsed.recent_titles:
        profile.target_roles = _normalize_str_list(parsed.recent_titles)
        if profile.target_roles:
            profile.role_intent = profile.target_roles[0]

    parts = []
    if parsed.recent_titles:
        parts.append("Recent roles: " + ", ".join(parsed.recent_titles))
    if parsed.skills:
        parts.append("Skills: " + ", ".join(parsed.skills))
    if parsed.years_of_experience:
        parts.append(f"Experience: {parsed.years_of_experience} years")
    distilled_text = "\n".join(parts) if parts else None
    if distilled_text:
        profile.distilled_text = distilled_text

    overrides = build_profile_patch(career_intent=career_intent)
    if profile.target_roles:
        overrides.update(build_profile_patch(profile_intent_roles=profile.target_roles))
    if structured_locations:
        profile.preferred_locations = structured_locations
        overrides.update(build_profile_patch(scraping_locations=structured_locations))
    elif suggested_locations:
        profile.preferred_locations = suggested_locations
        overrides.update(build_profile_patch(scraping_locations=suggested_locations))
    if structured_negatives:
        overrides.update(build_profile_patch(title_blocklist=structured_negatives))
    elif suggested_exclusions:
        overrides.update(build_profile_patch(title_blocklist=suggested_exclusions))
    if query_plan.get("title_queries") or query_plan.get("skill_queries") or query_plan.get("domain_queries"):
        profile.custom_search_queries = _normalize_str_list(
            (query_plan.get("title_queries") or [])
            + (query_plan.get("skill_queries") or [])
            + (query_plan.get("domain_queries") or [])
        )
    if overrides != (getattr(profile, "config_overrides", None) or {}):
        setattr(profile, "config_overrides", merge_profile_patch(getattr(profile, "config_overrides", None), overrides))
    if parsed.salary_lpa:
        profile.target_lpa = float(parsed.salary_lpa)
    if parsed.years_of_experience is not None:
        yoe = max(0, int(parsed.years_of_experience))
        profile.min_yoe = max(0, yoe - 2)
        profile.max_yoe = min(30, yoe + 2)
    sync_career_intent_override(profile)
    profile.candidate_profile = build_candidate_profile(parsed=parsed, profile=profile, resume_text=getattr(profile, "resume_text", None))
    return distilled_text
