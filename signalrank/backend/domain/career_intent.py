from __future__ import annotations

from typing import Iterable

from llm.resume_parser import ResumeParseResult


def _uniq_strs(values: Iterable[str] | None) -> list[str]:
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


def _uniq_dicts(items: Iterable[dict] | None, key_fields: tuple[str, ...]) -> list[dict]:
    seen: set[tuple[str, ...]] = set()
    result: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = tuple(str(item.get(field, "")).strip().lower() for field in key_fields)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _text_blob(parsed: ResumeParseResult) -> str:
    chunks: list[str] = []
    chunks.extend(parsed.skills or [])
    chunks.extend(parsed.recent_titles or [])
    chunks.extend(parsed.industries or [])
    chunks.extend(parsed.education or [])
    chunks.extend(parsed.suggested_search_queries or [])
    return " ".join(chunks).lower()


def _ensure_target_role(
    target_roles: list[dict],
    *,
    title: str,
    priority: str,
    confidence: float,
    evidence: list[str],
) -> None:
    for role in target_roles:
        if str(role.get("title", "")).strip().lower() == title.lower():
            return
    target_roles.insert(0, {
        "title": title,
        "priority": priority,
        "confidence": confidence,
        "evidence": evidence,
    })


def _ensure_archetype(
    archetypes: list[dict],
    *,
    archetype_id: str,
    label: str,
    priority: str,
    confidence: float,
    evidence: list[str],
) -> None:
    for item in archetypes:
        if str(item.get("id", "")).strip().lower() == archetype_id.lower():
            return
    archetypes.insert(0, {
        "id": archetype_id,
        "label": label,
        "priority": priority,
        "confidence": confidence,
        "evidence": evidence,
    })


def _ensure_negative(
    negative_targets: list[dict],
    *,
    label: str,
    reason: str,
    confidence: float,
) -> None:
    for item in negative_targets:
        if str(item.get("label", "")).strip().lower() == label.lower():
            return
    negative_targets.append({
        "label": label,
        "reason": reason,
        "confidence": confidence,
    })


def _ensure_false_friend(
    false_friends: list[dict],
    *,
    term: str,
    intended_meaning: str,
    exclude_meanings: list[str],
) -> None:
    for item in false_friends:
        if str(item.get("term", "")).strip().lower() == term.lower():
            return
    false_friends.append({
        "term": term,
        "intended_meaning": intended_meaning,
        "exclude_meanings": exclude_meanings,
    })


def _ensure_query_term(query_plan: dict, bucket: str, term: str) -> None:
    values = _uniq_strs(query_plan.get(bucket) or [])
    if term.lower() not in {value.lower() for value in values}:
        values.append(term)
    query_plan[bucket] = values


def _normalize_query_plan(query_plan: dict | None) -> dict:
    base = dict(query_plan or {})
    return {
        "title_queries": _uniq_strs(base.get("title_queries")),
        "skill_queries": _uniq_strs(base.get("skill_queries")),
        "domain_queries": _uniq_strs(base.get("domain_queries")),
        "negative_keywords": _uniq_strs(base.get("negative_keywords")),
    }


def build_career_intent_profile(parsed: ResumeParseResult) -> dict:
    query_plan = _normalize_query_plan(parsed.query_plan)
    target_roles = _uniq_dicts(parsed.target_roles, ("title",))
    archetypes = _uniq_dicts(parsed.career_archetypes, ("id",))
    negative_targets = _uniq_dicts(parsed.negative_targets, ("label",))
    false_friends = _uniq_dicts(parsed.false_friend_terms, ("term",))
    domains = _uniq_dicts(parsed.domains, ("name",))

    text = _text_blob(parsed)

    if "sap sd" in text or "order to cash" in text or "otc" in text or "s/4hana" in text:
        evidence = ["SAP/OTC terms found in resume"]
        _ensure_archetype(
            archetypes,
            archetype_id="erp_functional_consultant",
            label="ERP Functional Consultant",
            priority="primary",
            confidence=0.95,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="SAP SD Consultant",
            priority="primary",
            confidence=0.98,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="SAP OTC Functional Consultant",
            priority="secondary",
            confidence=0.9,
            evidence=evidence,
        )
        _ensure_negative(
            negative_targets,
            label="QA Automation",
            reason="Automation refers to ERP/business workflow, not software testing.",
            confidence=0.95,
        )
        _ensure_false_friend(
            false_friends,
            term="automation",
            intended_meaning="ERP/business process automation",
            exclude_meanings=["test automation", "qa automation"],
        )
        _ensure_query_term(query_plan, "title_queries", "SAP SD Consultant")
        _ensure_query_term(query_plan, "title_queries", "SAP S/4HANA SD Consultant")
        _ensure_query_term(query_plan, "title_queries", "SAP OTC Functional Consultant")
        _ensure_query_term(query_plan, "domain_queries", "Order to Cash")
        _ensure_query_term(query_plan, "negative_keywords", "Test Automation")
        _ensure_query_term(query_plan, "negative_keywords", "QA Engineer")

    innovation_markers = ("innovation", "emerging technolog", "prototype", "r&d", "computer vision", "iot")
    if any(marker in text for marker in innovation_markers):
        evidence = ["Innovation / R&D markers found in resume"]
        _ensure_archetype(
            archetypes,
            archetype_id="innovation_rd_engineer",
            label="Innovation / R&D Engineer",
            priority="primary",
            confidence=0.9,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="Innovation Engineer",
            priority="primary",
            confidence=0.88,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="Emerging Technologies Engineer",
            priority="secondary",
            confidence=0.82,
            evidence=evidence,
        )
        _ensure_query_term(query_plan, "title_queries", "Innovation Engineer")
        _ensure_query_term(query_plan, "title_queries", "Emerging Technologies Engineer")
        _ensure_query_term(query_plan, "title_queries", "R&D Engineer")
        _ensure_query_term(query_plan, "title_queries", "Prototype Engineer")
        _ensure_query_term(query_plan, "negative_keywords", "Generic Software Engineer")

    network_markers = ("network automation", "ansible", "router", "switch", "cloud networking", "network engineer")
    if any(marker in text for marker in network_markers):
        evidence = ["Network automation markers found in resume"]
        _ensure_archetype(
            archetypes,
            archetype_id="network_automation_engineer",
            label="Network Automation Engineer",
            priority="primary",
            confidence=0.92,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="Network Automation Engineer",
            priority="primary",
            confidence=0.95,
            evidence=evidence,
        )
        _ensure_target_role(
            target_roles,
            title="Infrastructure Automation Engineer",
            priority="secondary",
            confidence=0.85,
            evidence=evidence,
        )
        _ensure_false_friend(
            false_friends,
            term="automation",
            intended_meaning="network or infrastructure automation",
            exclude_meanings=["test automation", "qa automation"],
        )
        _ensure_query_term(query_plan, "title_queries", "Network Automation Engineer")
        _ensure_query_term(query_plan, "title_queries", "Infrastructure Automation Engineer")
        _ensure_query_term(query_plan, "title_queries", "Cloud Network Engineer")
        _ensure_query_term(query_plan, "negative_keywords", "AI Platform Engineer")

    priority_order = {"primary": 0, "secondary": 1, "adjacent": 2}
    target_roles = sorted(
        target_roles,
        key=lambda item: (
            priority_order.get(str(item.get("priority", "")).lower(), 9),
            -float(item.get("confidence", 0.0)),
            str(item.get("title", "")).lower(),
        ),
    )
    archetypes = sorted(
        archetypes,
        key=lambda item: (
            priority_order.get(str(item.get("priority", "")).lower(), 9),
            -float(item.get("confidence", 0.0)),
            str(item.get("label", "")).lower(),
        ),
    )

    summary_bits: list[str] = []
    if target_roles:
        summary_bits.append("Targeting " + ", ".join(role["title"] for role in target_roles[:3]))
    if parsed.years_of_experience:
        summary_bits.append(f"{parsed.years_of_experience} years experience")
    if parsed.skills:
        summary_bits.append("Core skills: " + ", ".join(parsed.skills[:6]))

    return {
        "version": "career_intent_v1",
        "candidate_summary": ". ".join(summary_bits),
        "seniority": {
            "level": _infer_seniority(parsed.years_of_experience),
            "confidence": 0.7 if parsed.years_of_experience is not None else 0.3,
            "evidence": [f"{parsed.years_of_experience} years of experience"] if parsed.years_of_experience is not None else [],
        },
        "career_archetypes": archetypes,
        "target_roles": target_roles,
        "domains": domains,
        "skills": {
            "core": _uniq_strs(parsed.skills),
            "tools": [],
            "platforms": [],
            "methods": [],
        },
        "industries": _uniq_strs(parsed.industries),
        "work_preferences": {
            "remote": "neutral",
            "employment_types": [],
            "locations": _uniq_strs(parsed.suggested_locations),
        },
        "negative_targets": negative_targets,
        "false_friend_terms": false_friends,
        "query_plan": query_plan,
        "ambiguities": _uniq_strs(parsed.ambiguities),
        "follow_up_questions": _uniq_dicts(parsed.follow_up_questions, ("id",)),
    }


def _infer_seniority(years_of_experience: int | None) -> str:
    if years_of_experience is None:
        return "mid"
    if years_of_experience <= 2:
        return "entry"
    if years_of_experience <= 5:
        return "mid"
    if years_of_experience <= 8:
        return "senior"
    if years_of_experience <= 12:
        return "lead"
    return "principal"
