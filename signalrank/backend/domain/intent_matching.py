from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from domain.artifact_versions import (
    JOB_INTENT_VERSION,
    MATCH_DECISION_VERSION,
    PROFILE_INTENT_VERSION,
    SCHEMA_VERSION,
    stable_digest,
)

PROFILE_INTENT_KEY = PROFILE_INTENT_VERSION
JOB_INTENT_KEY = JOB_INTENT_VERSION
MATCH_DECISION_KEY = "intent_shadow"


ROLE_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "sap_erp",
        (
            "sap",
            "s/4hana",
            "s4hana",
            "abap",
            "erp",
            "sap sd",
            "sap mm",
            "sap gts",
            "sap fico",
        ),
    ),
    (
        "ai_platform",
        (
            "ai platform",
            "ml platform",
            "mlops",
            "llmops",
            "model serving",
            "production ai",
        ),
    ),
    (
        "ai_ml",
        (
            "machine learning",
            "ml engineer",
            "ai engineer",
            "ai/ml",
            "genai",
            "gen ai",
            "llm",
            "rag",
            "agentic",
        ),
    ),
    (
        "network_automation",
        (
            "network automation",
            "network engineer",
            "cloud network",
            "routing",
            "switching",
            "firewall",
            "sd-wan",
            "servicenow",
            "resolve.io",
        ),
    ),
    (
        "emerging_tech",
        (
            "innovation",
            "emerging technologies",
            "creative technologist",
            "prototype",
            "prototyping",
            "r&d",
            "iot",
            "embedded",
            "robotics",
            "computer vision",
            "conversational ai",
            "chatbot",
            "voice ai",
        ),
    ),
    (
        "cybersecurity",
        (
            "cybersecurity",
            "security engineer",
            "zero trust",
            "sase",
            "ztna",
            "siem",
            "soc",
            "iam",
            "vulnerability",
        ),
    ),
    (
        "product_management",
        (
            "product manager",
            "product owner",
            "product strategy",
            "roadmap",
            "go to market",
        ),
    ),
    (
        "frontend",
        (
            "frontend",
            "front-end",
            "react",
            "vue",
            "angular",
            "ui engineer",
            "web developer",
        ),
    ),
    (
        "ux_design",
        (
            "ux design",
            "ui/ux",
            "user experience",
            "design engineer",
            "product designer",
            "ux engineer",
        ),
    ),
    (
        "data_analytics",
        (
            "data analyst",
            "business analyst",
            "analytics",
            "power bi",
            "tableau",
            "reporting",
        ),
    ),
    (
        "data_engineering",
        (
            "data engineer",
            "etl",
            "data pipeline",
            "data warehouse",
            "databricks",
            "spark",
        ),
    ),
    (
        "embedded_mechanical",
        (
            "embedded",
            "firmware",
            "mechanical",
            "hardware",
            "pcb",
            "microcontroller",
            "arduino",
            "raspberry pi",
            "sensors",
        ),
    ),
    (
        "backend_product",
        (
            "backend",
            "software engineer",
            "api",
            "microservices",
            "full stack",
            "distributed systems",
        ),
    ),
    (
        "platform_infra",
        (
            "platform engineer",
            "cloud engineer",
            "devops",
            "sre",
            "site reliability",
            "kubernetes",
            "terraform",
            "infrastructure",
        ),
    ),
    (
        "qa_test",
        (
            "qa",
            "quality assurance",
            "sdet",
            "test engineer",
            "engineer in test",
            "testing",
            "test automation",
        ),
    ),
    (
        "sales",
        (
            "sales",
            "account executive",
            "business development",
            "presales",
            "pre-sales",
        ),
    ),
    (
        "support",
        (
            "support engineer",
            "technical support",
            "helpdesk",
            "customer support",
            "technical account manager",
        ),
    ),
    (
        "people_management",
        (
            "engineering manager",
            "project manager",
            "program manager",
            "director",
            "head of",
            "vp",
            "vice president",
        ),
    ),
)

FAMILY_LABELS = {
    "sap_erp": "SAP / ERP",
    "ai_platform": "AI Platform / MLOps",
    "ai_ml": "AI / ML",
    "network_automation": "Network / Infrastructure Automation",
    "emerging_tech": "Innovation / Emerging Tech",
    "cybersecurity": "Cybersecurity",
    "product_management": "Product Management",
    "frontend": "Frontend / Web",
    "ux_design": "UX / Product Design",
    "data_analytics": "Data Analytics",
    "data_engineering": "Data Engineering",
    "embedded_mechanical": "Embedded / Mechanical",
    "backend_product": "Backend / Product Engineering",
    "platform_infra": "Platform / Infrastructure",
    "qa_test": "QA / Test",
    "sales": "Sales",
    "support": "Support",
    "people_management": "People / Program Management",
    "general": "General",
}

SENIORITY_ORDER = {"junior": 0, "mid": 1, "senior": 2, "staff": 3, "principal": 4}
HARD_NEGATIVE_FAMILIES = {"qa_test", "sales", "support", "people_management"}
ROLE_STOPWORDS = {
    "engineer",
    "developer",
    "senior",
    "sr",
    "lead",
    "staff",
    "principal",
    "consultant",
    "specialist",
    "architect",
    "manager",
}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _dedupe(values: Iterable[Any] | None, *, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        item = _clean(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _has_phrase(text: str, phrase: str) -> bool:
    normalized = _norm(text)
    phrase_norm = _norm(phrase)
    if phrase_norm.isalnum():
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])",
                normalized,
            )
        )
    return phrase_norm in normalized


def _infer_role_families(text: str) -> list[str]:
    scores: list[tuple[int, int, str]] = []
    for order, (family, terms) in enumerate(ROLE_FAMILY_RULES):
        hits = sum(1 for term in terms if _has_phrase(text, term))
        if hits:
            scores.append((-hits, order, family))
    return [family for _hits, _order, family in sorted(scores)[:4]] or ["general"]


def _explicitly_allows_hard_family(text: str, family: str) -> bool:
    lowered = _norm(text)
    if family == "qa_test":
        return any(
            term in lowered
            for term in (
                "qa engineer",
                "qa automation",
                "quality assurance",
                "sdet",
                "test engineer",
                "engineer in test",
                "test automation",
            )
        )
    if family == "sales":
        return any(
            term in lowered
            for term in (
                "account executive",
                "business development",
                "sales engineer",
                "sales manager",
                "sales representative",
                "presales",
                "pre-sales",
            )
        )
    if family == "support":
        return any(
            term in lowered
            for term in (
                "support engineer",
                "technical support",
                "customer support",
                "helpdesk",
                "technical account manager",
            )
        )
    if family == "people_management":
        return (
            any(
                term in lowered
                for term in (
                    "engineering manager",
                    "project manager",
                    "program manager",
                    "director",
                    "head of",
                    "cto",
                    "vice president",
                )
            )
            and "product manager" not in lowered
        )
    return False


def _infer_seniority(text: str) -> str:
    lowered = _norm(text)
    if any(term in lowered for term in ("principal", "distinguished", "director")):
        return "principal"
    if any(term in lowered for term in ("staff", "lead", "manager", "head of", "vp")):
        return "staff"
    if any(term in lowered for term in ("senior", "sr.", "sr ", " ii", " iii")):
        return "senior"
    if any(term in lowered for term in ("junior", "entry", "intern", "associate")):
        return "junior"
    yoe = re.search(r"\b(\d+)\+?\s*years\b", lowered)
    if yoe:
        years = int(yoe.group(1))
        if years <= 2:
            return "junior"
        if years <= 5:
            return "mid"
        if years <= 9:
            return "senior"
        return "staff"
    return "mid"


def _role_tokens(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9+#.]+", _norm(value))
        if len(token) >= 3 and token not in ROLE_STOPWORDS
    }
    return tokens


def _role_title_overlap(profile_roles: list[str], job_titles: list[str]) -> bool:
    job_text = " ".join(job_titles)
    for role in profile_roles:
        role_norm = _norm(role)
        if role_norm and role_norm in _norm(job_text):
            return True
        tokens = _role_tokens(role)
        if tokens and len(tokens & _role_tokens(job_text)) >= min(2, len(tokens)):
            return True
    return False


def _family_title_evidence(family: str, job_titles: list[str]) -> bool:
    title_text = " ".join(job_titles)
    for known_family, terms in ROLE_FAMILY_RULES:
        if known_family != family:
            continue
        return any(_has_phrase(title_text, term) for term in terms)
    return False


def _skill_overlap(left: list[str], right: list[str]) -> tuple[set[str], float]:
    left_norm = {_norm(item) for item in left if _norm(item)}
    right_norm = {_norm(item) for item in right if _norm(item)}
    if not left_norm:
        return set(), 0.0
    matches = {
        item
        for item in left_norm
        if item in right_norm
        or any(item in other or other in item for other in right_norm)
    }
    return matches, len(matches) / max(1, len(left_norm))


def _evidence(source: str, text: str, *, limit: int = 240) -> dict[str, str]:
    return {"source": source, "text": _clean(text)[:limit]}


def _constraints_for_text(text: str, *, role_families: list[str]) -> list[str]:
    constraints: list[str] = []
    lowered = _norm(text)
    if "people_management" in role_families or _explicitly_allows_hard_family(
        lowered, "people_management"
    ):
        constraints.append("people_management")
    if "qa_test" in role_families or _explicitly_allows_hard_family(lowered, "qa_test"):
        constraints.append("qa_test")
    if "sales" in role_families or _explicitly_allows_hard_family(lowered, "sales"):
        constraints.append("sales")
    if "support" in role_families or _explicitly_allows_hard_family(lowered, "support"):
        constraints.append("support")
    if any(
        term in lowered for term in ("junior", "entry level", "entry-level", "intern")
    ):
        constraints.append("junior")
    if "associate" in lowered and "associate principal" not in lowered:
        constraints.append("associate")
    if "contract" in lowered:
        constraints.append("contract")
    return _dedupe(constraints, limit=12)


def build_profile_intent(
    candidate_profile: dict[str, Any] | None,
    *,
    resume_text: str = "",
    llm_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = candidate_profile or {}
    target_roles = _dedupe(profile.get("target_roles_primary"), limit=12)
    adjacent_roles = _dedupe(profile.get("target_roles_adjacent"), limit=12)
    negative_roles = _dedupe(profile.get("negative_roles"), limit=12)
    must_have = _dedupe(profile.get("must_have_skills"), limit=24)
    nice_to_have = _dedupe(profile.get("good_to_have_skills"), limit=24)
    domains = _dedupe(profile.get("domains"), limit=12)
    target_blob = " ".join(target_roles)
    adjacent_blob = " ".join(adjacent_roles)
    target_families = _infer_role_families(target_blob)
    adjacent_families = [
        family for family in _infer_role_families(adjacent_blob) if family != "general"
    ]
    target_text = " ".join([*target_roles, *adjacent_roles])
    target_families = [
        family
        for family in target_families
        if family not in HARD_NEGATIVE_FAMILIES
        or _explicitly_allows_hard_family(target_text, family)
    ] or ["general"]
    adjacent_families = [
        family
        for family in adjacent_families
        if family not in HARD_NEGATIVE_FAMILIES
        or _explicitly_allows_hard_family(target_text, family)
    ]
    role_families = _dedupe(
        [
            *target_families,
            *adjacent_families,
            *_infer_role_families(" ".join(must_have)),
        ],
        limit=6,
    )
    role_families = [
        family
        for family in role_families
        if family not in HARD_NEGATIVE_FAMILIES
        or _explicitly_allows_hard_family(target_text, family)
    ] or ["general"]
    blob = " ".join(
        [
            *target_roles,
            *adjacent_roles,
            *must_have,
            *nice_to_have,
            resume_text[:1500],
        ]
    )
    confidence = 0.86
    if role_families == ["general"]:
        confidence = 0.52
    elif not target_roles:
        confidence = 0.62
    intent = {
        "artifact_version": PROFILE_INTENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "target_roles": target_roles,
        "adjacent_roles": adjacent_roles,
        "negative_roles": negative_roles,
        "primary_role_families": target_families,
        "adjacent_role_families": adjacent_families,
        "role_families": role_families,
        "seniority_min": profile.get("seniority_band") or _infer_seniority(blob),
        "seniority_max": "principal",
        "domains": domains,
        "must_have_skills": must_have,
        "nice_to_have_skills": nice_to_have,
        "hard_constraints": _constraints_for_text(
            " ".join(negative_roles),
            role_families=_infer_role_families(" ".join(negative_roles)),
        ),
        "confidence": round(confidence, 3),
        "source": "deterministic",
        "evidence_spans": [
            _evidence("target_roles", ", ".join(target_roles)),
            _evidence("domains", ", ".join(domains)),
            _evidence("skills", ", ".join(must_have[:8])),
        ],
    }
    intent = merge_llm_intent(intent, llm_intent, expected_kind="profile")
    intent["intent_fingerprint"] = stable_digest(intent)
    return intent


def build_job_intent(
    *,
    title: str | None,
    company: str | None = None,
    description: str | None = None,
    location: str | None = None,
    job_profile: dict[str, Any] | None = None,
    llm_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = job_profile or {}
    title_text = _clean(title)
    description_text = _clean(description)
    role_titles = _dedupe(
        [title_text, *(profile.get("role_titles_normalized") or [])], limit=8
    )
    required_skills = _dedupe(profile.get("required_skills"), limit=24)
    preferred_skills = _dedupe(profile.get("preferred_skills"), limit=24)
    role_blob = " ".join(
        [
            title_text,
            str(profile.get("role_family") or ""),
            str(profile.get("domain") or ""),
            description_text[:1800],
            " ".join(required_skills),
        ]
    )
    title_families = _infer_role_families(title_text)
    role_families = (
        title_families
        if title_families != ["general"]
        else _infer_role_families(role_blob)
    )
    role_family = role_families[0]
    constraint_text = " ".join([title_text, str(profile.get("role_family") or "")])
    constraints = _constraints_for_text(
        constraint_text,
        role_families=title_families if title_families != ["general"] else [],
    )
    confidence = 0.84 if role_family != "general" else 0.46
    if not description_text:
        confidence = min(confidence, 0.52)
    intent = {
        "artifact_version": JOB_INTENT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "role_titles": role_titles,
        "role_family": role_family,
        "role_family_label": FAMILY_LABELS.get(role_family, role_family),
        "seniority": profile.get("seniority_band") or _infer_seniority(role_blob),
        "domains": _dedupe(
            [
                profile.get("domain"),
                profile.get("role_family"),
                FAMILY_LABELS.get(role_family),
            ],
            limit=8,
        ),
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "responsibilities": _dedupe(
            [description_text[:500] if description_text else ""], limit=3
        ),
        "hard_constraints": constraints,
        "risk_flags": _dedupe(profile.get("red_flags"), limit=12),
        "confidence": round(confidence, 3),
        "source": "deterministic",
        "evidence_spans": [
            _evidence("title", title_text),
            _evidence("company", company or ""),
            _evidence("location", location or ""),
            _evidence("description", description_text),
        ],
    }
    intent = merge_llm_intent(intent, llm_intent, expected_kind="job")
    intent["intent_fingerprint"] = stable_digest(intent)
    return intent


def merge_llm_intent(
    base_intent: dict[str, Any],
    llm_intent: dict[str, Any] | None,
    *,
    expected_kind: str,
) -> dict[str, Any]:
    if not isinstance(llm_intent, dict) or not llm_intent:
        return dict(base_intent)
    merged = dict(base_intent)
    list_fields = {
        "target_roles",
        "adjacent_roles",
        "negative_roles",
        "role_families",
        "domains",
        "must_have_skills",
        "nice_to_have_skills",
        "hard_constraints",
        "role_titles",
        "required_skills",
        "preferred_skills",
        "responsibilities",
        "risk_flags",
        "evidence_spans",
    }
    scalar_fields = {
        "role_family",
        "role_family_label",
        "seniority",
        "seniority_min",
        "seniority_max",
    }
    for field in list_fields:
        if field in llm_intent:
            if field == "hard_constraints":
                merged[field] = _dedupe(
                    [*(base_intent.get(field) or []), *(llm_intent.get(field) or [])],
                    limit=16,
                )
            elif field == "evidence_spans":
                merged[field] = [
                    *(base_intent.get(field) or []),
                    *(llm_intent.get(field) or []),
                ][:8]
            else:
                merged[field] = _dedupe(llm_intent.get(field), limit=24)
    for field in scalar_fields:
        if _clean(llm_intent.get(field)):
            merged[field] = _clean(llm_intent.get(field))
    llm_confidence = float(llm_intent.get("confidence") or 0.0)
    if llm_confidence:
        merged["confidence"] = round(
            max(float(base_intent.get("confidence") or 0.0), min(llm_confidence, 0.96)),
            3,
        )
    merged["source"] = f"{base_intent.get('source') or 'deterministic'}+llm"
    merged["llm_intent_kind"] = expected_kind
    return merged


def needs_llm_fallback(intent: dict[str, Any]) -> bool:
    confidence = float(intent.get("confidence") or 0.0)
    role_families = intent.get("role_families") or [intent.get("role_family")]
    return confidence < 0.62 or "general" in {str(item) for item in role_families}


def intent_cache_key(
    *,
    kind: str,
    text_fingerprint: str,
    model_version: str,
    intent_version: str,
) -> str:
    return stable_digest(
        {
            "kind": kind,
            "text_fingerprint": text_fingerprint,
            "model_version": model_version,
            "intent_version": intent_version,
            "schema_version": SCHEMA_VERSION,
        }
    )


INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_roles": {"type": "array", "items": {"type": "string"}},
        "adjacent_roles": {"type": "array", "items": {"type": "string"}},
        "negative_roles": {"type": "array", "items": {"type": "string"}},
        "role_families": {"type": "array", "items": {"type": "string"}},
        "role_titles": {"type": "array", "items": {"type": "string"}},
        "role_family": {"type": "string"},
        "seniority": {"type": "string"},
        "seniority_min": {"type": "string"},
        "seniority_max": {"type": "string"},
        "domains": {"type": "array", "items": {"type": "string"}},
        "must_have_skills": {"type": "array", "items": {"type": "string"}},
        "nice_to_have_skills": {"type": "array", "items": {"type": "string"}},
        "required_skills": {"type": "array", "items": {"type": "string"}},
        "preferred_skills": {"type": "array", "items": {"type": "string"}},
        "responsibilities": {"type": "array", "items": {"type": "string"}},
        "hard_constraints": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "evidence_spans": {"type": "array", "items": {"type": "object"}},
    },
    "additionalProperties": True,
}


async def extract_intent_with_llm(
    *,
    llm_client: Any,
    kind: str,
    text: str,
    base_intent: dict[str, Any],
    max_tokens: int = 900,
) -> dict[str, Any]:
    if llm_client is None:
        return dict(base_intent)
    system = (
        "Extract resume/job intent as JSON only. Use concise normalized role-family "
        "slugs, preserve hard negatives, and do not score the match."
    )
    user = f"KIND: {kind}\n" f"BASE_INTENT: {base_intent}\n\n" f"TEXT:\n{text[:6000]}"
    response = await llm_client.llm_json(
        system=system,
        user=user,
        json_schema=INTENT_SCHEMA,
        schema_name=f"{kind}_intent",
        max_tokens=max_tokens,
    )
    if not isinstance(response, dict) or response.get("_error"):
        return dict(base_intent)
    return merge_llm_intent(base_intent, response, expected_kind=kind)


def _is_family_allowed(profile_intent: dict[str, Any], family: str) -> bool:
    profile_families = set(
        profile_intent.get("primary_role_families")
        or profile_intent.get("role_families")
        or []
    )
    if family in profile_families:
        return True
    if family == "ai_ml" and "ai_platform" in profile_families:
        return True
    if family == "platform_infra" and "ai_platform" in profile_families:
        return True
    return False


def _negative_role_hit(
    profile_intent: dict[str, Any], job_intent: dict[str, Any]
) -> str | None:
    job_blob = _norm(
        " ".join(
            [
                *(job_intent.get("role_titles") or []),
                job_intent.get("role_family") or "",
                " ".join(job_intent.get("domains") or []),
            ]
        )
    )
    for role in profile_intent.get("negative_roles") or []:
        if _norm(role) and _norm(role) in job_blob:
            return str(role)
    return None


def _band_from_score(score: float) -> str:
    if score >= 75:
        return "strong_fit"
    if score >= 55:
        return "adjacent_fit"
    if score >= 35:
        return "weak_fit"
    return "reject"


def score_intent_match(
    profile_intent: dict[str, Any],
    job_intent: dict[str, Any],
    *,
    current_score: float = 0.0,
) -> dict[str, Any]:
    family = str(job_intent.get("role_family") or "general")
    reasons_up: list[str] = []
    reasons_down: list[str] = []
    hard_constraints: list[str] = []

    negative_hit = _negative_role_hit(profile_intent, job_intent)
    if negative_hit:
        hard_constraints.append(f"negative_role:{negative_hit}")

    profile_families = set(profile_intent.get("role_families") or [])
    allowed_hard = set(profile_families)
    for constraint in job_intent.get("hard_constraints") or []:
        if (
            constraint == "associate"
            and profile_intent.get("seniority_min") != "junior"
        ):
            hard_constraints.append("associate_role")
        if constraint in HARD_NEGATIVE_FAMILIES and constraint not in allowed_hard:
            hard_constraints.append(f"hard_negative_family:{constraint}")
        if constraint == "junior" and profile_intent.get("seniority_min") not in {
            "junior",
            "mid",
        }:
            hard_constraints.append("junior_role")

    direct_family = _is_family_allowed(profile_intent, family)
    title_match = _role_title_overlap(
        profile_intent.get("target_roles") or [], job_intent.get("role_titles") or []
    )
    family_title_match = _family_title_evidence(
        family,
        job_intent.get("role_titles") or [],
    )
    adjacent_match = _role_title_overlap(
        profile_intent.get("adjacent_roles") or [], job_intent.get("role_titles") or []
    )
    skill_matches, skill_ratio = _skill_overlap(
        profile_intent.get("must_have_skills") or [],
        [
            *(job_intent.get("required_skills") or []),
            *(job_intent.get("preferred_skills") or []),
            *(job_intent.get("role_titles") or []),
            *(job_intent.get("domains") or []),
        ],
    )
    domain_matches, domain_ratio = _skill_overlap(
        profile_intent.get("domains") or [], job_intent.get("domains") or []
    )

    score = 24.0 + min(12.0, 0.12 * max(0.0, min(100.0, current_score)))
    if direct_family:
        score += 30.0
        reasons_up.append(f"direct_family:{family}")
    elif family != "general":
        reasons_down.append(f"non_target_family:{family}")
        score += 4.0
    else:
        reasons_down.append("unknown_role_family")

    if title_match:
        score += 18.0
        reasons_up.append("target_title_evidence")
    elif adjacent_match:
        score += 10.0
        reasons_up.append("adjacent_title_evidence")
    elif direct_family and family_title_match:
        score += 12.0
        reasons_up.append("family_title_evidence")

    if skill_ratio:
        score += min(18.0, 24.0 * skill_ratio)
        reasons_up.append(f"skill_overlap:{len(skill_matches)}")
    else:
        reasons_down.append("no_must_have_skill_overlap")

    if domain_ratio:
        score += min(10.0, 12.0 * domain_ratio)
        reasons_up.append("domain_overlap")

    confidence = min(
        float(profile_intent.get("confidence") or 0.0),
        float(job_intent.get("confidence") or 0.0),
    )
    if confidence < 0.62:
        reasons_down.append("low_intent_confidence")
        score = min(score, 54.9)

    if hard_constraints:
        score = min(score, 34.0)
    elif not direct_family and not (title_match or adjacent_match or skill_ratio):
        reasons_down.append("non_target_without_direct_evidence")
        score = min(score, 34.0)
    elif not direct_family and not title_match:
        score = min(score, 54.9)
    elif family == "general" and not (title_match and skill_ratio and domain_ratio):
        score = min(score, 54.9)
    elif family_title_match and not (title_match or skill_ratio or domain_ratio):
        reasons_down.append("family_title_without_skill_or_domain_evidence")
        score = min(score, 54.9)
    elif (
        direct_family
        and (title_match or family_title_match)
        and (skill_ratio or domain_ratio)
    ):
        score = max(score, 76.0)
    elif direct_family and (title_match or skill_ratio or domain_ratio):
        score = max(score, 62.0)

    score = round(max(0.0, min(100.0, score)), 1)
    return {
        "artifact_version": MATCH_DECISION_VERSION,
        "schema_version": SCHEMA_VERSION,
        "score": score,
        "band": _band_from_score(score),
        "confidence": round(confidence, 3),
        "reasons_up": _dedupe(reasons_up, limit=12),
        "reasons_down": _dedupe(reasons_down, limit=12),
        "hard_constraints": _dedupe(hard_constraints, limit=12),
        "profile_intent_version": PROFILE_INTENT_VERSION,
        "job_intent_version": JOB_INTENT_VERSION,
    }
