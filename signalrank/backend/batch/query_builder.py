from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from api.config import settings
from batch.context import deep_merge, load_base_config
from domain.intent_matching import HARD_NEGATIVE_FAMILIES, PROFILE_INTENT_KEY
from domain.role_taxonomy import ROLE_QUERY_ALIASES, ROLE_QUERY_EXPANSIONS


@dataclass
class SearchQuery:
    term: str
    location: str
    country: str


@dataclass(frozen=True)
class QueryCandidate:
    term: str
    query_type: str
    role_family: str
    priority: int
    confidence: float
    risk_flags: tuple[str, ...]
    evidence: tuple[str, ...]


FAMILY_QUERY_PRESETS: dict[str, dict[str, tuple[str, ...]]] = {
    "sap_erp": {
        "title_aliases": (
            "SAP SD Consultant",
            "SAP S/4HANA SD Consultant",
            "SAP OTC Functional Consultant",
            "SAP Order to Cash Consultant",
            "SAP SD",
            "SAP OTC",
            "SAP Functional Consultant",
        ),
        "anchors": ("SAP SD", "S/4HANA", "Order to Cash", "ABAP"),
        "negative": ("QA Engineer", "Test Automation"),
    },
    "ai_platform": {
        "title_aliases": (
            "AI Platform Engineer",
            "MLOps Engineer",
            "ML Platform Engineer",
            "LLMOps Engineer",
        ),
        "anchors": ("MLOps", "LLMOps", "model serving", "Kubernetes"),
        "negative": ("Data Scientist", "Applied Scientist", "Research Scientist"),
    },
    "ai_ml": {
        "title_aliases": (
            "AI/ML Engineer",
            "Machine Learning Engineer",
            "GenAI Engineer",
            "LLM Engineer",
        ),
        "anchors": ("machine learning", "GenAI", "LLM", "RAG"),
        "negative": (),
    },
    "network_automation": {
        "title_aliases": (
            "Network Automation Engineer",
            "NetDevOps Engineer",
            "Network Operations Automation Engineer",
            "Network Infrastructure Automation Engineer",
            "Cloud Network Engineer",
            "Network Engineer Automation",
            "Network Automation",
        ),
        "anchors": ("network automation", "ServiceNow", "firewall", "routing"),
        "negative": ("QA Automation", "AI Platform Engineer"),
    },
    "frontend": {
        "title_aliases": ("Frontend Engineer", "React Developer", "UI Engineer"),
        "anchors": ("React", "TypeScript", "Vue", "Angular"),
        "negative": ("Backend Engineer", "QA Engineer"),
    },
    "cybersecurity": {
        "title_aliases": (
            "Cybersecurity Engineer",
            "Security Engineer",
            "Zero Trust Security Engineer",
        ),
        "anchors": ("zero trust", "IAM", "SIEM", "vulnerability"),
        "negative": ("Network Engineer",),
    },
    "data_analytics": {
        "title_aliases": ("Data Analyst", "Analytics Engineer", "BI Analyst"),
        "anchors": ("SQL", "Tableau", "Power BI", "analytics"),
        "negative": ("Data Engineer",),
    },
    "data_engineering": {
        "title_aliases": ("Data Engineer", "ETL Engineer", "Data Platform Engineer"),
        "anchors": ("ETL", "Spark", "Databricks", "data pipeline"),
        "negative": ("Data Analyst",),
    },
    "product_management": {
        "title_aliases": (
            "Product Manager",
            "Product Owner",
            "Technical Product Manager",
        ),
        "anchors": ("roadmap", "product strategy", "analytics", "discovery"),
        "negative": ("Engineering Manager", "Project Manager"),
    },
    "embedded_mechanical": {
        "title_aliases": ("Embedded Engineer", "Firmware Engineer", "IoT Engineer"),
        "anchors": ("firmware", "sensors", "microcontroller", "hardware"),
        "negative": (),
    },
    "emerging_tech": {
        "title_aliases": (
            "Creative Technologist",
            "Computer Vision AI Architect",
            "Conversational AI Architect",
            "AI Innovation Engineer",
            "AI Solutions Architect IoT",
            "IoT Prototype Engineer",
            "Rapid Prototyping Engineer",
            "Computer Vision Engineer",
            "Conversational AI Engineer",
        ),
        "anchors": (
            "IoT",
            "computer vision",
            "conversational AI",
            "innovation",
            "prototype",
            "R&D",
        ),
        "negative": ("Generic Software Engineer",),
    },
    "backend_product": {
        "title_aliases": ("Backend Engineer", "API Engineer", "Product Engineer"),
        "anchors": ("API", "microservices", "distributed systems"),
        "negative": ("Frontend Engineer", "QA Engineer"),
    },
    "platform_infra": {
        "title_aliases": (
            "Platform Engineer",
            "Cloud Infrastructure Engineer",
            "SRE",
        ),
        "anchors": ("Kubernetes", "Terraform", "infrastructure", "DevOps"),
        "negative": ("QA Engineer",),
    },
}

BROAD_QUERY_TERMS = {
    "software engineer",
    "ai engineer",
    "data engineer",
    "platform engineer",
    "consultant",
    "manager",
    "support",
    "qa",
    "sales",
    "developer",
    "engineer",
}
NON_ROLE_TITLE_PHRASES = (
    "certified",
    "certification",
    "resume",
    "curriculum vitae",
)
ROLE_SEGMENT_SEPARATORS = re.compile(r"\s+(?:[|·•]|[-–—]{1,2})\s+")
STANDALONE_SKILL_TERMS = {
    "ansible",
    "ci/cd",
    "docker",
    "java",
    "kubernetes",
    "python",
    "react",
    "servicenow",
    "terraform",
    "typescript",
}
GENERIC_ANCHOR_TERMS = {
    "agile",
    "aws",
    "azure",
    "cloud",
    "git",
    "gcp",
    "java",
    "python",
    "sql",
}
TITLE_ANCHOR_TERMS = {
    "analyst",
    "architect",
    "consultant",
    "developer",
    "engineer",
    "lead",
    "manager",
    "owner",
    "scientist",
    "specialist",
    "technologist",
}
ENTRY_LEVEL_TERMS = (
    "associate",
    "entry level",
    "entry-level",
    "fresher",
    "graduate engineer trainee",
    "intern",
    "internship",
    "junior",
    "trainee",
)
HARD_FAMILY_TERMS = {
    "qa_test": ("qa", "quality assurance", "sdet", "test engineer", "test automation"),
    "sales": ("sales", "account executive", "business development", "presales"),
    "support": ("support", "technical support", "helpdesk", "customer support"),
    "people_management": (
        "engineering manager",
        "project manager",
        "program manager",
        "director",
        "head of",
    ),
}
QUERY_PLAN_DEBUG_KEY = "intent_query_planner_v1"


def _get_profile_attr(profile: Any, name: str, default: Any = None) -> Any:
    value = getattr(profile, name, default)
    if type(value).__module__ == "unittest.mock":
        return default
    return value


def _config_overrides(profile: Any) -> dict:
    overrides = _get_profile_attr(profile, "config_overrides", None)
    return overrides if isinstance(overrides, dict) else {}


def _planner_config(profile: Any) -> dict:
    cfg = deep_merge(load_base_config(), _config_overrides(profile))
    return cfg.get("scraping", {}).get("intent_query_planner", {}) or {}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _norm(value: Any) -> str:
    return _clean(value).lower()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _norm(value)))


def _dedupe(values: list[Any] | tuple[Any, ...], *, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = _clean(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _profile_intent(profile: Any) -> dict:
    candidate_profile = _get_profile_attr(profile, "candidate_profile", None)
    if isinstance(candidate_profile, dict):
        intent = candidate_profile.get(PROFILE_INTENT_KEY)
        if isinstance(intent, dict):
            return intent
        return {
            "target_roles": _as_list(candidate_profile.get("target_roles_primary")),
            "adjacent_roles": _as_list(candidate_profile.get("target_roles_adjacent")),
            "negative_roles": _as_list(candidate_profile.get("negative_roles")),
            "primary_role_families": _as_list(
                candidate_profile.get("primary_role_families")
            ),
            "role_families": _as_list(candidate_profile.get("role_families")),
            "must_have_skills": _as_list(candidate_profile.get("must_have_skills")),
            "hard_constraints": _as_list(candidate_profile.get("hard_constraints")),
            "confidence": candidate_profile.get("confidence", 0.5),
        }
    roles = _as_list(_get_profile_attr(profile, "target_roles", []))
    overrides = _config_overrides(profile)
    if not roles:
        roles = _as_list((overrides.get("profile_intent") or {}).get("roles"))
    return {
        "target_roles": roles,
        "adjacent_roles": [],
        "negative_roles": [],
        "primary_role_families": [],
        "role_families": ["general"],
        "must_have_skills": [],
        "hard_constraints": [],
        "confidence": 0.5,
    }


def _career_query_plan(profile: Any) -> dict:
    career_intent = _config_overrides(profile).get("career_intent") or {}
    return career_intent.get("query_plan") or {}


def _negative_terms(profile: Any, intent: dict) -> list[str]:
    query_plan = _career_query_plan(profile)
    preset_terms: list[str] = []
    for family in _as_list(intent.get("primary_role_families")) + _as_list(
        intent.get("role_families")
    ):
        preset_terms.extend(FAMILY_QUERY_PRESETS.get(family, {}).get("negative", ()))
    return _dedupe(
        [
            *_as_list(query_plan.get("negative_keywords")),
            *_as_list(intent.get("negative_roles")),
            *preset_terms,
        ],
        limit=24,
    )


def _expand_role_terms(role: str) -> list[str]:
    normalized = role.strip().lower()
    expansions = ROLE_QUERY_EXPANSIONS.get(normalized)
    if expansions:
        ordered = [role.strip()]
        ordered.extend(
            expanded
            for expanded in expansions
            if expanded.strip().lower() != normalized
        )
        return ordered
    for canonical, aliases in ROLE_QUERY_ALIASES.items():
        alias_values = (canonical, *aliases)
        if any(alias in normalized or normalized in alias for alias in alias_values):
            expansions = list(ROLE_QUERY_EXPANSIONS.get(canonical, (role.strip(),)))
            return [
                role.strip(),
                *[
                    expanded
                    for expanded in expansions
                    if expanded.strip().lower() != normalized
                ],
            ]

    normalized_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    best_canonical: str | None = None
    best_score = 0
    for canonical, aliases in ROLE_QUERY_ALIASES.items():
        for alias in (canonical, *aliases):
            alias_tokens = set(re.findall(r"[a-z0-9]+", alias))
            score = len(normalized_tokens & alias_tokens)
            if score > best_score and score >= 2:
                best_score = score
                best_canonical = canonical
    if best_canonical:
        expansions = list(ROLE_QUERY_EXPANSIONS.get(best_canonical, (role.strip(),)))
        return [
            role.strip(),
            *[
                expanded
                for expanded in expansions
                if expanded.strip().lower() != normalized
            ],
        ]
    return [role.strip()]


def _legacy_terms(profile: Any, *, max_terms: int | None) -> list[str]:
    query_plan = _career_query_plan(profile)
    roles = _as_list(_get_profile_attr(profile, "target_roles", []))
    if not roles:
        roles = _as_list(
            (_config_overrides(profile).get("profile_intent") or {}).get("roles")
        )

    custom = _as_list(query_plan.get("title_queries"))
    custom += _as_list(query_plan.get("domain_queries"))
    custom += _as_list(_get_profile_attr(profile, "custom_search_queries", []))
    negative_terms = [
        _norm(term) for term in _as_list(query_plan.get("negative_keywords"))
    ]

    seen: set[str] = set()
    terms: list[str] = []
    for role in roles:
        for expanded in _expand_role_terms(role):
            key = _norm(expanded)
            if key and key not in seen:
                if any(negative in key for negative in negative_terms):
                    continue
                seen.add(key)
                terms.append(_clean(expanded))
    for term in custom:
        key = _norm(term)
        if key and key not in seen:
            if any(negative in key for negative in negative_terms):
                continue
            seen.add(key)
            terms.append(_clean(term))
    return terms[: max_terms or settings.scraper_max_terms]


def _primary_families(intent: dict) -> list[str]:
    families = _as_list(intent.get("primary_role_families"))
    if not families:
        families = _as_list(intent.get("role_families"))
    return [family for family in families if family and family != "general"]


def _allowed_hard_families(intent: dict) -> set[str]:
    return set(_primary_families(intent)) & HARD_NEGATIVE_FAMILIES


def _is_unknown_intent(intent: dict) -> bool:
    confidence = float(intent.get("confidence") or 0.0)
    families = _as_list(intent.get("primary_role_families")) or _as_list(
        intent.get("role_families")
    )
    return confidence < 0.62 or not families or families == ["general"]


def _anchor_skills(intent: dict, family: str) -> list[str]:
    preset = FAMILY_QUERY_PRESETS.get(family, {})
    values = [*preset.get("anchors", ()), *_as_list(intent.get("must_have_skills"))]
    anchors: list[str] = []
    for value in values:
        item = _clean(value)
        key = item.lower()
        if not item or key in GENERIC_ANCHOR_TERMS:
            continue
        if len(item) < 4:
            continue
        anchors.append(item)
    return _dedupe(anchors, limit=4)


def _has_title_anchor(term: str) -> bool:
    return bool(_tokens(term) & TITLE_ANCHOR_TERMS)


def _is_probably_not_role_title(term: str) -> bool:
    lowered = _norm(term)
    if any(phrase in lowered for phrase in NON_ROLE_TITLE_PHRASES):
        return True
    return False


def _compact_role_query_terms(role: str) -> list[str]:
    cleaned = _clean(role)
    if not cleaned:
        return []
    if _is_probably_not_role_title(cleaned):
        return []
    pieces = _dedupe(ROLE_SEGMENT_SEPARATORS.split(cleaned), limit=8)
    title_like = [
        piece
        for piece in pieces
        if _has_title_anchor(piece) and not _is_probably_not_role_title(piece)
    ]
    if title_like:
        return _dedupe(title_like, limit=3)
    if len(_tokens(cleaned)) <= 6 and _has_title_anchor(cleaned):
        return [cleaned]
    return []


def _target_query_terms(target_roles: list[str]) -> list[str]:
    terms: list[str] = []
    for role in target_roles:
        terms.extend(_compact_role_query_terms(role))
    return _dedupe(terms, limit=8)


def _candidate(
    *,
    term: str,
    query_type: str,
    role_family: str,
    priority: int,
    confidence: float,
    evidence: tuple[str, ...],
) -> QueryCandidate:
    return QueryCandidate(
        term=_clean(term),
        query_type=query_type,
        role_family=role_family or "general",
        priority=priority,
        confidence=round(float(confidence or 0.0), 3),
        risk_flags=(),
        evidence=evidence,
    )


def _candidate_pool(profile: Any) -> list[QueryCandidate]:
    intent = _profile_intent(profile)
    query_plan = _career_query_plan(profile)
    confidence = float(intent.get("confidence") or 0.0)
    raw_target_roles = _dedupe(_as_list(intent.get("target_roles")), limit=8)
    target_roles = _target_query_terms(raw_target_roles)
    adjacent_roles = _dedupe(_as_list(intent.get("adjacent_roles")), limit=6)
    families = _primary_families(intent)
    if not families:
        families = ["general"]

    candidates: list[QueryCandidate] = []
    for role in target_roles:
        family = families[0]
        candidates.append(
            _candidate(
                term=role,
                query_type="exact_title",
                role_family=family,
                priority=100,
                confidence=confidence,
                evidence=("profile_intent.target_roles",),
            )
        )
        if not _is_unknown_intent(intent):
            for expanded in _expand_role_terms(role)[1:3]:
                candidates.append(
                    _candidate(
                        term=expanded,
                        query_type="exact_title",
                        role_family=family,
                        priority=94,
                        confidence=confidence,
                        evidence=("role_taxonomy.expansion",),
                    )
                )

    if not _is_unknown_intent(intent):
        for family_index, family in enumerate(families[:3]):
            preset = FAMILY_QUERY_PRESETS.get(family, {})
            for alias_index, alias in enumerate(preset.get("title_aliases", ())[:6]):
                candidates.append(
                    _candidate(
                        term=alias,
                        query_type="family_title",
                        role_family=family,
                        priority=88 - (family_index * 8) - alias_index,
                        confidence=confidence,
                        evidence=(f"family:{family}",),
                    )
                )
            anchors = _anchor_skills(intent, family)
            for role in target_roles[:3]:
                for anchor in anchors[:2]:
                    if _norm(anchor) in _norm(role):
                        continue
                    candidates.append(
                        _candidate(
                            term=f"{role} {anchor}",
                            query_type="title_skill",
                            role_family=family,
                            priority=82 - (family_index * 8),
                            confidence=confidence,
                            evidence=("profile_intent.target_roles", "anchor_skill"),
                        )
                    )
            if confidence >= 0.75:
                for anchor in anchors[:2]:
                    candidates.append(
                        _candidate(
                            term=anchor,
                            query_type="domain",
                            role_family=family,
                            priority=40 - (family_index * 8),
                            confidence=confidence,
                            evidence=("high_confidence_family_domain",),
                        )
                    )

        for role in adjacent_roles[:4]:
            adjacent_terms = _compact_role_query_terms(role)
            if not adjacent_terms:
                continue
            adjacent = adjacent_terms[0]
            candidates.append(
                _candidate(
                    term=adjacent,
                    query_type="adjacent_title",
                    role_family=families[0],
                    priority=64,
                    confidence=confidence,
                    evidence=("profile_intent.adjacent_roles",),
                )
            )

        for term in _as_list(query_plan.get("title_queries")):
            candidates.append(
                _candidate(
                    term=term,
                    query_type="exact_title",
                    role_family=families[0],
                    priority=86,
                    confidence=confidence,
                    evidence=("career_intent.query_plan.title_queries",),
                )
            )
        for term in _as_list(query_plan.get("domain_queries")):
            candidates.append(
                _candidate(
                    term=term,
                    query_type="domain",
                    role_family=families[0],
                    priority=38,
                    confidence=confidence,
                    evidence=("career_intent.query_plan.domain_queries",),
                )
            )
    return candidates


def _term_has_hard_family(term: str, family: str) -> bool:
    lowered = _norm(term)
    return any(phrase in lowered for phrase in HARD_FAMILY_TERMS.get(family, ()))


def _term_matches_negative(term: str, negative_terms: list[str]) -> bool:
    lowered = _norm(term)
    return any(
        _norm(negative) and _norm(negative) in lowered for negative in negative_terms
    )


def _is_standalone_skill(term: str) -> bool:
    return _norm(term) in STANDALONE_SKILL_TERMS


def _is_domain_only(candidate: QueryCandidate) -> bool:
    if candidate.query_type != "domain":
        return False
    return not (_tokens(candidate.term) & TITLE_ANCHOR_TERMS)


def _is_entry_level_term(term: str) -> bool:
    lowered = _norm(term)
    if any(value in lowered for value in ENTRY_LEVEL_TERMS):
        return True
    return bool(
        re.search(
            r"\b(analyst|consultant|developer|engineer|specialist)\s+i\b",
            lowered,
        )
    )


def _has_family_evidence(term: str, family: str) -> bool:
    lowered = _norm(term)
    preset = FAMILY_QUERY_PRESETS.get(family, {})
    phrases = [*preset.get("title_aliases", ()), *preset.get("anchors", ())]
    return any(_norm(phrase) and _norm(phrase) in lowered for phrase in phrases)


def _is_broad_unanchored(candidate: QueryCandidate, target_roles: list[str]) -> bool:
    term = _norm(candidate.term)
    if term in {_norm(role) for role in target_roles}:
        return False
    if term in BROAD_QUERY_TERMS:
        return candidate.query_type not in {"exact_title", "title_skill"}
    return False


def _with_risk(candidate: QueryCandidate, risk_flags: list[str]) -> QueryCandidate:
    return QueryCandidate(
        term=candidate.term,
        query_type=candidate.query_type,
        role_family=candidate.role_family,
        priority=candidate.priority,
        confidence=candidate.confidence,
        risk_flags=tuple(_dedupe(risk_flags, limit=12)),
        evidence=candidate.evidence,
    )


def _gate_candidates(
    profile: Any,
    candidates: list[QueryCandidate],
) -> tuple[list[QueryCandidate], list[QueryCandidate]]:
    intent = _profile_intent(profile)
    negative_terms = _negative_terms(profile, intent)
    target_roles = _as_list(intent.get("target_roles"))
    target_entry_level = any(_is_entry_level_term(role) for role in target_roles)
    allowed_hard = _allowed_hard_families(intent)
    accepted: list[QueryCandidate] = []
    rejected: list[QueryCandidate] = []
    seen: set[str] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (-item.priority, -item.confidence, item.term.lower()),
    ):
        key = candidate.term.lower()
        if not key or key in seen:
            continue
        risk_flags = list(candidate.risk_flags)
        if _term_matches_negative(candidate.term, negative_terms):
            risk_flags.append("negative_keyword")
        if _is_standalone_skill(candidate.term):
            risk_flags.append("standalone_skill")
        if _is_domain_only(candidate):
            risk_flags.append("domain_only")
        if _is_entry_level_term(candidate.term) and not target_entry_level:
            risk_flags.append("entry_level_role")
        if candidate.query_type == "adjacent_title" and not _has_family_evidence(
            candidate.term, candidate.role_family
        ):
            risk_flags.append("weak_adjacent_title")
        for family in HARD_NEGATIVE_FAMILIES:
            if family not in allowed_hard and _term_has_hard_family(
                candidate.term, family
            ):
                risk_flags.append(f"hard_negative_family:{family}")
        if _is_broad_unanchored(candidate, target_roles):
            risk_flags.append("broad_unanchored")
        gated = _with_risk(candidate, risk_flags)
        seen.add(key)
        if risk_flags:
            rejected.append(gated)
        else:
            accepted.append(gated)
    return accepted, rejected


def build_query_candidates(
    profile: Any,
    *,
    max_terms: int | None = None,
) -> list[QueryCandidate]:
    accepted, _rejected = _gate_candidates(profile, _candidate_pool(profile))
    limit = max_terms or int(_planner_config(profile).get("default_max_terms") or 8)
    return accepted[:limit]


def _queries_from_terms(
    profile: Any,
    terms: list[str],
    *,
    expand_locations: bool = False,
) -> list[SearchQuery]:
    locations = _as_list(_get_profile_attr(profile, "preferred_locations", []))
    if not locations:
        locations = _as_list(
            (_config_overrides(profile).get("scraping") or {}).get("locations")
        )

    default_country = settings.scraper_default_country
    if not locations:
        locations = [default_country]
    if expand_locations:
        locations = _dedupe(
            [
                *locations,
                "Remote",
                default_country,
            ],
            limit=int(_planner_config(profile).get("default_max_locations") or 3),
        )

    country_like = {default_country.lower(), "remote", "india", "worldwide"}
    queries: list[SearchQuery] = []
    seen_query_keys: set[tuple[str, str]] = set()
    for term in terms:
        for loc in locations:
            city = "" if str(loc).lower() in country_like else str(loc)
            key = (term.lower(), city.lower())
            if key in seen_query_keys:
                continue
            seen_query_keys.add(key)
            queries.append(
                SearchQuery(term=term, location=city, country=default_country)
            )
            if len(queries) >= 50:
                return queries
    return queries


def _candidate_payload(candidate: QueryCandidate) -> dict[str, Any]:
    return asdict(candidate) | {
        "risk_flags": list(candidate.risk_flags),
        "evidence": list(candidate.evidence),
    }


def build_query_plan_debug(
    profile: Any,
    *,
    max_terms: int | None = None,
) -> dict[str, Any]:
    candidates = _candidate_pool(profile)
    accepted, rejected = _gate_candidates(profile, candidates)
    intent_limit = max_terms or int(
        _planner_config(profile).get("default_max_terms") or 8
    )
    intent_candidates = accepted[:intent_limit]
    current_terms = _legacy_terms(profile, max_terms=max_terms)
    intent_terms = [candidate.term for candidate in intent_candidates]
    risk_flags = sorted(
        {risk for candidate in [*accepted, *rejected] for risk in candidate.risk_flags}
    )
    gates = {
        "no_standalone_skills": not any(
            "standalone_skill" in candidate.risk_flags for candidate in accepted
        ),
        "no_hard_negative_terms": not any(
            any(
                risk.startswith("hard_negative_family") for risk in candidate.risk_flags
            )
            for candidate in accepted
        ),
        "no_broad_unanchored_terms": not any(
            "broad_unanchored" in candidate.risk_flags for candidate in accepted
        ),
        "max_terms_respected": len(intent_terms) <= intent_limit,
    }
    return {
        "version": QUERY_PLAN_DEBUG_KEY,
        "shadow_enabled": bool(_planner_config(profile).get("shadow_enabled", True)),
        "use_for_scrape": bool(_planner_config(profile).get("use_for_scrape", False)),
        "current_terms": current_terms,
        "intent_terms": intent_terms,
        "accepted_candidates": [
            _candidate_payload(candidate) for candidate in intent_candidates
        ],
        "rejected_candidates": [
            _candidate_payload(candidate) for candidate in rejected
        ],
        "risk_flags": risk_flags,
        "gates": gates | {"passes": all(gates.values())},
        "counts": {
            "current_terms": len(current_terms),
            "intent_terms": len(intent_terms),
            "rejected_candidates": len(rejected),
        },
    }


def build_profile_scan_plan(
    profile: Any,
    *,
    max_terms: int | None = None,
) -> dict[str, Any]:
    debug = build_query_plan_debug(profile, max_terms=max_terms)
    intent = _profile_intent(profile)
    negative_terms = _negative_terms(profile, intent)
    queries = build_queries(profile, max_terms=max_terms)
    locations = _dedupe(
        [query.location or query.country for query in queries],
        limit=12,
    )
    search_terms = _dedupe([query.term for query in queries], limit=24)
    accepted_candidates = list(debug.get("accepted_candidates") or [])
    rejected_candidates = list(debug.get("rejected_candidates") or [])
    title_positive = _dedupe(
        [
            *(candidate.get("term") for candidate in accepted_candidates),
            *_as_list((_career_query_plan(profile) or {}).get("title_queries")),
        ],
        limit=24,
    )
    confidence_values = [
        float(candidate.get("confidence") or 0.0)
        for candidate in accepted_candidates
        if isinstance(candidate, dict)
    ]
    confidence = round(
        sum(confidence_values) / len(confidence_values),
        3,
    ) if confidence_values else float(intent.get("confidence") or 0.0)
    return {
        "version": "profile_scan_plan_v1",
        "source": "profile_intent",
        "use_for_scrape": bool(debug.get("use_for_scrape")),
        "confidence": round(float(confidence or 0.0), 3),
        "search_terms": search_terms,
        "workday_search_terms": search_terms,
        "locations": locations,
        "title_filter": {
            "positive": title_positive,
            "negative": negative_terms,
        },
        "accepted_terms": accepted_candidates,
        "rejected_terms": rejected_candidates,
        "risk_flags": list(debug.get("risk_flags") or []),
        "gates": dict(debug.get("gates") or {}),
        "counts": dict(debug.get("counts") or {}),
    }


def build_queries(profile: Any, *, max_terms: int | None = None) -> list[SearchQuery]:
    planner_cfg = _planner_config(profile)
    use_intent = bool(planner_cfg.get("use_for_scrape", False))
    if use_intent:
        planner_default = int(planner_cfg.get("default_max_terms") or 8)
        term_limit = (
            max_terms
            if max_terms and max_terms > settings.scraper_max_terms
            else planner_default
        )
        terms = [
            candidate.term
            for candidate in build_query_candidates(profile, max_terms=term_limit)
        ]
    else:
        terms = _legacy_terms(profile, max_terms=max_terms)
    return _queries_from_terms(profile, terms, expand_locations=use_intent)
