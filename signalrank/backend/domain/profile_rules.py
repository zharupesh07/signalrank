from __future__ import annotations

import re
from typing import Iterable

from domain.skills import extract_skills_from_texts

BASE_STRONG_TITLE_PENALTY_PATTERNS = [
    r"\bsupport\b",
    r"\bsupport specialist\b",
    r"\btools support\b",
    r"\btester\b",
    r"\btest automation\b",
    r"\btest engineer\b",
    r"\bperformance tester\b",
    r"\bqa engineer\b",
    r"\bquality assurance\b",
]

BASE_ADJACENT_TITLE_PATTERNS = [
    r"\barchitect\b",
    r"\bplatform architect\b",
    r"\btech architect\b",
    r"\bcloud architect\b",
    r"\benterprise data platform\b",
    r"\bcloud data engineer\b",
    r"\bdata engineer\b",
    r"\binfrastructure engineer\b",
    r"\bcloud platform\b",
    r"\bdevops\b",
    r"\bcloud engineer\b",
]

BASE_HYBRID_TITLE_PATTERNS = [
    r"\bbackend\b",
    r"\bfull stack\b",
    r"\bsoftware engineer\b",
    r"\bjava\b",
    r"\bpython developer\b",
    r"\bapplication developer\b",
]


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    if re.fullmatch(r"[a-z0-9_+/\- ]+", phrase):
        pattern = r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return phrase in text


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(_contains_phrase(text, term) for term in terms)


def _match_count(text: str, terms: Iterable[str]) -> int:
    return sum(1 for term in terms if _contains_phrase(text, term))


def infer_profile_archetypes(
    resume_text: str,
    profile_roles: Iterable[str] | None,
    cfg: dict,
) -> list[str]:
    resume_text_lower = (resume_text or "").lower()
    roles_text = " ".join(str(r) for r in (profile_roles or [])).lower()
    skills = set(extract_skills_from_texts([resume_text or ""], cfg)[0])
    archetypes: list[str] = []

    ai_signals = 0
    if skills & {
        "llm", "agents", "rag", "genai", "mlops",
        "deep_learning", "ml_fundamentals", "nlp", "conversational_ai",
    }:
        ai_signals += 1
    if _has_any(roles_text, ["ai", "ml", "llm", "mlops", "genai", "machine learning", "applied scientist"]):
        ai_signals += 1
    if _has_any(resume_text_lower, ["agentic", "genai", "llm", "rag", "machine learning", "mlops"]):
        ai_signals += 1
    if ai_signals >= 2:
        archetypes.append("ai_builder")

    data_signals = 0
    if skills & {"data_engineering", "etl", "airflow", "kafka", "spark", "databricks", "dbt"}:
        data_signals += 1
    if _has_any(roles_text, ["data engineer", "analytics engineer", "data scientist", "data platform"]):
        data_signals += 1
    if _has_any(resume_text_lower, ["etl", "airflow", "spark", "kafka", "data pipeline", "warehouse"]):
        data_signals += 1
    if data_signals >= 2:
        archetypes.append("data_engineer")

    platform_signals = 0
    if skills & {
        "aws", "gcp", "azure", "kubernetes", "docker",
        "terraform", "ci_cd", "monitoring", "idp", "linux",
    }:
        platform_signals += 1
    if _has_any(roles_text, ["platform", "devops", "sre", "cloud infrastructure", "developer productivity"]):
        platform_signals += 1
    if _has_any(resume_text_lower, ["kubernetes", "terraform", "ci/cd", "oidc", "rbac", "cloud-native", "internal developer platform", "idp"]):
        platform_signals += 1
    if platform_signals >= 1:
        archetypes.append("platform_infra")

    security_signals = 0
    if skills & {"security", "networking"}:
        security_signals += 1
    if _has_any(roles_text, ["security", "application security", "product security"]):
        security_signals += 1
    if _has_any(resume_text_lower, ["zero-trust", "oidc", "rbac", "secrets isolation", "product security"]):
        security_signals += 1
    if security_signals >= 2:
        archetypes.append("security")

    enterprise_signals = 0
    if skills & {"sap", "servicenow_tool"}:
        enterprise_signals += 1
    if _has_any(roles_text, ["sap", "abap", "servicenow", "salesforce", "workday", "oracle ebs"]):
        enterprise_signals += 1
    if _has_any(resume_text_lower, ["sap", "abap", "servicenow", "salesforce", "s/4hana", "itsm", "oracle ebs", "workday", "peoplesoft"]):
        enterprise_signals += 1
    if enterprise_signals >= 1:
        archetypes.append("enterprise_apps")

    sap_functional_signals = 0
    if _has_any(
        roles_text,
        [
            "sap sd",
            "sap mm",
            "sap fico",
            "sap fi/co",
            "sap functional",
            "sap s/4hana",
            "sap gts",
        ],
    ):
        sap_functional_signals += 1
    if _has_any(
        resume_text_lower,
        [
            "sap sd",
            "sap mm",
            "sap fico",
            "sap fi/co",
            "s/4hana",
            "order to cash",
            "order-to-cash",
            "otc",
            "sales and distribution",
            "sales & distribution",
            "gts",
            "functional consultant",
        ],
    ):
        sap_functional_signals += 1
    if sap_functional_signals >= 1:
        archetypes.append("sap_functional")

    sap_sd_signals = 0
    if _has_any(
        roles_text,
        [
            "sap sd",
            "sales and distribution",
            "sap gts",
        ],
    ):
        sap_sd_signals += 1
    if _has_any(
        resume_text_lower,
        [
            "sap sd",
            "sales and distribution",
            "sales & distribution",
            "order to cash",
            "order-to-cash",
            "otc",
            "gts",
        ],
    ):
        sap_sd_signals += 1
    if sap_sd_signals >= 1:
        archetypes.append("sap_sd")

    innovation_signals = 0
    if skills & {
        "iot", "robotics", "conversational_ai", "blockchain", "ar_vr",
        "prototyping", "innovation_management",
    }:
        innovation_signals += 1
    if _has_any(
        roles_text,
        [
            "innovation",
            "emerging technologies",
            "r&d",
            "research engineer",
            "technical expert innovation",
            "creative technologist",
        ],
    ):
        innovation_signals += 1
    if _has_any(
        resume_text_lower,
        [
            "innovation", "emerging technolog", "rapid poc", "rapid pot", "poc", "prototype",
            "mvp", "iot", "robotics", "conversational ai", "blockchain", "ar/vr",
            "innovation lab", "workshop facilitation", "go-to-market", "gtm",
        ],
    ):
        innovation_signals += 1
    if innovation_signals >= 2:
        archetypes.append("innovation_rd_engineer")

    network_automation_signals = 0
    if skills & {"networking", "ansible", "python", "aws", "docker"}:
        network_automation_signals += 1
    if _has_any(
        roles_text,
        [
            "network automation",
            "infrastructure automation",
            "cloud network",
            "cloud networking",
            "network engineer",
            "network operations",
        ],
    ):
        network_automation_signals += 1
    if _has_any(
        resume_text_lower,
        [
            "network automation",
            "infrastructure automation",
            "cloud network",
            "cloud networking",
            "network engineer",
            "network operations",
            "firewall",
            "load balancer",
            "ssl certificate",
        ],
    ):
        network_automation_signals += 1
    if network_automation_signals >= 2:
        archetypes.append("network_automation_engineer")

    if not archetypes and (skills & {"javascript", "java", "go", "python"} or "engineer" in roles_text):
        archetypes.append("software_generalist")
    if not archetypes:
        archetypes.append("generalist")
    return archetypes


def build_profile_title_rules(archetypes: Iterable[str]) -> dict[str, list[str]]:
    archetypes = set(archetypes)

    strong = list(BASE_STRONG_TITLE_PENALTY_PATTERNS)
    adjacent = list(BASE_ADJACENT_TITLE_PATTERNS)
    hybrid = list(BASE_HYBRID_TITLE_PATTERNS)

    if "ai_builder" in archetypes:
        strong.extend([
            r"\bcustomer engineer\b",
            r"\bsolutions engineer\b",
            r"\bsolutions architect\b",
            r"\bfield solutions architect\b",
            r"\bconsultant\b",
        ])
        if "enterprise_apps" not in archetypes:
            strong.extend([
                r"\bsap\b",
                r"\babap\b",
                r"\bservicenow\b",
                r"\bsalesforce\b",
            ])
        if "security" not in archetypes:
            strong.append(r"\bsecurity consultant\b")
        if "platform_infra" not in archetypes:
            strong.extend([r"\bsite reliability\b", r"\bsre\b"])
    else:
        adjacent = [p for p in adjacent if p not in {
            r"\bdata engineer\b",
            r"\bcloud data engineer\b",
            r"\bdevops\b",
            r"\bcloud engineer\b",
            r"\binfrastructure engineer\b",
        }]
        hybrid = [p for p in hybrid if p not in {
            r"\bsoftware engineer\b",
            r"\bapplication developer\b",
        }]

    if "data_engineer" in archetypes:
        adjacent = [p for p in adjacent if p not in {
            r"\bdata engineer\b",
            r"\bcloud data engineer\b",
            r"\benterprise data platform\b",
        }]

    if "platform_infra" in archetypes:
        adjacent = [p for p in adjacent if p not in {
            r"\bdevops\b",
            r"\bcloud engineer\b",
            r"\binfrastructure engineer\b",
            r"\bcloud platform\b",
        }]
        strong = [p for p in strong if p not in {r"\bsite reliability\b", r"\bsre\b"}]

    if "security" in archetypes:
        strong = [p for p in strong if p not in {r"\bsecurity consultant\b"}]

    if "enterprise_apps" in archetypes:
        adjacent = [p for p in adjacent if p not in {r"\barchitect\b"}]

    if "sap_functional" in archetypes:
        strong.extend([
            r"\bbasis\b",
            r"\babap\b",
            r"\bbtp\b",
            r"\bai\b",
            r"\bml\b",
            r"\bmachine learning\b",
            r"\bgenai\b",
            r"\bllm\b",
            r"\bdata scientist\b",
            r"\bdata engineer\b",
            r"\bsoftware engineer\b",
            r"\bdeveloper\b",
            r"\bdevops\b",
            r"\bplatform\b",
            r"\bsecurity\b",
            r"\bproduct manager\b",
            r"\bproject manager\b",
            r"\bprogram manager\b",
        ])
        adjacent.extend([
            r"\barchitect\b",
            r"\bintegration engineer\b",
            r"\bfull stack\b",
        ])

    if "sap_sd" in archetypes:
        strong.extend([
            r"\blinux\b",
            r"\bpacemaker\b",
            r"\bqa\b",
            r"\btest\b",
            r"\bsalesforce\b",
            r"\bfico\b",
            r"\bfi/co\b",
            r"\bp2p\b",
            r"\bprocure to pay\b",
            r"\bariba\b",
            r"\bppds\b",
            r"\bcpi\b",
            r"\bmdm\b",
            r"\bewm\b",
            r"\btm\b",
            r"\bhcm\b",
            r"\bcrm\b",
            r"\bbw\b",
            r"\bbpc\b",
            r"\bsuccessfactors\b",
        ])

    if "innovation_rd_engineer" in archetypes:
        strong.extend([
            r"\bcustomer engineer\b",
            r"\bsolutions engineer\b",
            r"\bsolutions architect\b",
            r"\bsales engineer\b",
            r"\baccount executive\b",
            r"\bsupport\b",
            r"\btest automation\b",
        ])
        adjacent.extend([
            r"\bsoftware engineer\b",
            r"\bai engineer\b",
            r"\bdata engineer\b",
            r"\bsite reliability\b",
            r"\bsre\b",
        ])
        hybrid.extend([
            r"\bapplication engineer\b",
            r"\bproduct engineer\b",
        ])

    if "network_automation_engineer" in archetypes:
        strong.extend([
            r"\bqa\b",
            r"\btest\b",
            r"\bmanual tester\b",
            r"\bsupport\b",
            r"\bfrontend\b",
            r"\bwordpress\b",
            r"\bshopify\b",
            r"\bsap\b",
            r"\bbusiness analyst\b",
            r"\bdata analyst\b",
            r"\bproduct manager\b",
            r"\bai engineer\b",
            r"\bmachine learning\b",
            r"\bbackend engineer\b",
            r"\bplatform engineer\b",
            r"\bdevops\b",
            r"\bsre\b",
            r"\bsite reliability\b",
            r"\bsecurity engineer\b",
        ])
        adjacent.extend([
            r"\bdevops\b",
            r"\bsite reliability\b",
            r"\bsre\b",
            r"\bplatform engineer\b",
            r"\binfrastructure engineer\b",
            r"\bcloud engineer\b",
        ])
        hybrid.extend([
            r"\bsystems engineer\b",
            r"\breliability engineer\b",
        ])

    return {
        "strong": sorted(set(strong)),
        "adjacent": sorted(set(adjacent)),
        "hybrid": sorted(set(hybrid)),
    }


def build_profile_positive_terms(archetypes: Iterable[str]) -> dict[str, list[str]]:
    """Return tiered positive terms: core (must match ≥1) and broad (only if core also matches).

    Backward-compatible: callers that pass a list[str] to
    text_matches_profile_positive_terms() still work — treated as all-core.
    """
    archetypes = set(archetypes)
    core: list[str] = []
    broad: list[str] = []

    if "sap_sd" in archetypes:
        core.extend([
            "sap sd",
            "sd consultant",
            "functional analyst",
            "sales and distribution",
            "sales & distribution",
            "order to cash",
            "order-to-cash",
            "otc",
            "s/4hana sd",
            "sap gts",
        ])
        broad.extend([
            "gts",
            "pricing",
            "functional analyst",
            "functional consultant",
        ])

    if "ai_builder" in archetypes:
        core.extend([
            "machine learning",
            "ml engineer",
            "llm",
            "large language model",
            "genai",
            "gen ai",
            "ai engineer",
            "nlp",
        ])
        broad.extend([
            "python",
            "data scientist",
            "deep learning",
        ])

    if "platform_infra" in archetypes:
        core.extend([
            "devops",
            "sre",
            "site reliability",
            "platform engineer",
            "kubernetes",
            "infrastructure engineer",
        ])
        broad.extend([
            "cloud",
            "aws",
            "gcp",
            "azure",
        ])

    if "data_engineer" in archetypes:
        core.extend([
            "data engineer",
            "etl",
            "data pipeline",
            "data platform",
        ])
        broad.extend([
            "sql",
            "python",
            "spark",
        ])

    if "innovation_rd_engineer" in archetypes:
        core.extend([
            "innovation engineer",
            "innovation technologist",
            "emerging technologies",
            "emerging technologies engineer",
            "r&d",
            "r&d engineer",
            "research and development engineer",
            "technical innovation consultant",
            "prototype",
            "poc",
            "mvp",
            "iot",
            "robotics",
            "innovation lab",
        ])
        broad.extend([
            "innovation",
            "conversational ai",
            "blockchain",
            "ar/vr",
            "workshop",
            "go-to-market",
            "gtm",
        ])

    if "network_automation_engineer" in archetypes:
        core.extend([
            "network automation",
            "network automation engineer",
            "infrastructure automation",
            "infrastructure automation engineer",
            "cloud network",
            "cloud networking",
            "cloud network engineer",
            "network reliability",
            "network reliability engineer",
            "network devops engineer",
            "network operations automation",
            "firewall",
            "load balancer",
        ])
        broad.extend([
            "network engineer",
            "network operations",
            "ansible",
            "python",
            "servicenow",
            "ssl certificate",
        ])

    return {
        "core": sorted(set(core)),
        "broad": sorted(set(broad)),
    }


def refine_profile_roles_for_ranking(
    profile_roles: Iterable[str] | None,
    *,
    resume_text: str,
    archetypes: Iterable[str],
) -> list[str]:
    roles = [str(role).strip() for role in (profile_roles or []) if str(role).strip()]
    role_map = {role.lower(): role for role in roles}
    archetypes = set(archetypes)
    resume_lower = (resume_text or "").lower()

    if {"ai_builder", "platform_infra"}.issubset(archetypes) and _has_any(
        resume_lower,
        ["ai platform", "mlops", "llmops", "platform engineer", "internal developer platform", "idp"],
    ):
        preferred = [
            "AI Platform Engineer",
            "MLOps Engineer",
            "ML Platform Engineer",
            "LLMOps Engineer",
            "Platform Engineer",
            "Machine Learning Engineer",
        ]
        generic_terms = ("data scientist", "applied scientist", "research scientist", "software engineer")
        refined: list[str] = []
        for title in preferred:
            existing = role_map.get(title.lower())
            refined.append(existing or title)
        for role in roles:
            lowered = role.lower()
            if lowered in {title.lower() for title in refined}:
                continue
            if any(term in lowered for term in generic_terms):
                continue
            refined.append(role)
        return refined[:6]

    if "innovation_rd_engineer" in archetypes:
        preferred = [
            "Innovation Engineer",
            "Emerging Technologies Engineer",
            "R&D Engineer",
            "Technical Innovation Consultant",
            "Innovation Technologist",
        ]
        generic_terms = (
            "software engineer",
            "ai engineer",
            "data engineer",
            "customer engineer",
            "solutions engineer",
            "platform engineer",
            "site reliability",
            "sre",
            "devops",
            "security",
            "backend engineer",
            "cloud engineer",
        )
        refined: list[str] = []
        for title in preferred:
            existing = role_map.get(title.lower())
            refined.append(existing or title)
        for role in roles:
            lowered = role.lower()
            if lowered in {title.lower() for title in refined}:
                continue
            if any(term in lowered for term in generic_terms):
                continue
            refined.append(role)
        return refined[:6]

    if "network_automation_engineer" in archetypes:
        preferred = [
            "Network Automation Engineer",
            "Infrastructure Automation Engineer",
            "Cloud Network Engineer",
            "Network Reliability Engineer",
            "Network DevOps Engineer",
            "Cloud Infrastructure Automation Engineer",
        ]
        generic_terms = (
            "qa",
            "test",
            "support",
            "frontend",
            "sap",
            "business analyst",
            "product manager",
            "ai engineer",
            "machine learning",
            "data engineer",
            "backend engineer",
            "platform engineer",
            "security engineer",
        )
        refined: list[str] = []
        for title in preferred:
            existing = role_map.get(title.lower())
            refined.append(existing or title)
        for role in roles:
            lowered = role.lower()
            if lowered in {title.lower() for title in refined}:
                continue
            if any(term in lowered for term in generic_terms):
                continue
            refined.append(role)
        return refined[:6]

    if "sap_sd" in archetypes:
        preferred = [
            "SAP SD Consultant",
            "SAP OTC Functional Consultant",
            "SAP S/4HANA SD Consultant",
            "SAP Sales and Distribution Consultant",
            "SAP Order to Cash Consultant",
            "SAP SD Functional Analyst",
        ]
        generic_terms = ("basis", "abap developer", "qa", "support specialist", "linux administrator")
        refined: list[str] = []
        for title in preferred:
            existing = role_map.get(title.lower())
            refined.append(existing or title)
        for role in roles:
            lowered = role.lower()
            if lowered in {title.lower() for title in refined}:
                continue
            if any(term in lowered for term in generic_terms):
                continue
            refined.append(role)
        return refined[:6]

    return roles


def profile_description_alignment_multiplier(
    title: str,
    description: str,
    cfg: dict,
) -> float:
    archetypes = set((cfg.get("ranking", {}) or {}).get("profile_archetypes", []))
    if not archetypes:
        return 1.0

    text = f"{title or ''} {description or ''}".lower()
    multiplier = 1.0

    if {"ai_builder", "platform_infra"}.issubset(archetypes):
        title_text = (title or "").lower()
        desc_text = (description or "").lower()
        ai_terms = [
            "machine learning", "ml engineer", "ai engineer", "llm", "genai", "rag",
            "agentic", "ai/ml", "artificial intelligence",
        ]
        platform_terms = [
            "platform engineer", "mlops", "llmops", "kubernetes", "terraform", "docker",
            "ci/cd", "infrastructure", "deployment", "observability", "site reliability",
            "sre", "cloud run", "rbac", "oidc",
        ]
        platform_title_terms = [
            "platform engineer", "ai platform", "ml platform", "mlops", "llmops",
            "site reliability", "sre", "devops",
        ]
        research_terms = [
            "data scientist", "applied scientist", "research scientist", "research engineer",
        ]

        ai_hits = _match_count(text, ai_terms)
        platform_hits = _match_count(desc_text, platform_terms)
        platform_title_hits = _match_count(title_text, platform_title_terms)
        has_research_title = _has_any(title_text, research_terms)

        if ai_hits >= 1 and (platform_title_hits >= 1 or platform_hits >= 2):
            multiplier *= 1.08
        elif has_research_title and platform_title_hits == 0:
            multiplier *= 0.88
        elif ai_hits >= 1 and platform_hits == 0 and platform_title_hits == 0:
            multiplier *= 0.92
        elif platform_title_hits >= 1 and ai_hits == 0:
            multiplier *= 0.96

    if "innovation_rd_engineer" in archetypes:
        title_text = (title or "").lower()
        desc_text = (description or "").lower()
        innovation_terms = [
            "innovation engineer", "innovation technologist", "technical innovation consultant",
            "emerging technologies", "emerging technologies engineer", "r&d", "r&d engineer",
            "research and development engineer", "prototype", "poc", "mvp",
            "iot", "robotics", "innovation lab", "workshop", "go-to-market", "gtm",
        ]
        generic_delivery_terms = [
            "software engineer", "ai engineer", "solutions engineer", "customer engineer",
            "site reliability", "data engineer", "application engineer",
        ]
        innovation_hits = _match_count(f"{title_text} {desc_text}", innovation_terms)
        generic_hits = _match_count(title_text, generic_delivery_terms)

        if innovation_hits >= 2:
            multiplier *= 1.10
        elif innovation_hits == 1:
            multiplier *= 1.04
        elif generic_hits >= 1:
            multiplier *= 0.65
        elif _has_any(title_text, ["ai engineer", "software engineer", "platform engineer", "site reliability", "sre", "devops", "security"]):
            multiplier *= 0.62

    if "network_automation_engineer" in archetypes:
        title_text = (title or "").lower()
        desc_text = (description or "").lower()
        network_terms = [
            "network automation",
            "network automation engineer",
            "infrastructure automation",
            "infrastructure automation engineer",
            "cloud network",
            "cloud networking",
            "cloud network engineer",
            "firewall",
            "load balancer",
            "network operations automation",
            "network reliability",
            "network reliability engineer",
        ]
        off_target_terms = [
            "qa",
            "manual tester",
            "support",
            "frontend",
            "sap",
            "business analyst",
        ]
        network_hits = _match_count(f"{title_text} {desc_text}", network_terms)
        off_target_hits = _match_count(title_text, off_target_terms)
        generic_title_hits = _match_count(
            title_text,
            [
                "ai engineer",
                "machine learning",
                "data engineer",
                "backend engineer",
                "security engineer",
                "platform engineer",
                "devops",
                "sre",
                "site reliability",
            ],
        )

        if network_hits >= 2:
            multiplier *= 1.10
        elif network_hits == 1:
            multiplier *= 1.04
        elif off_target_hits >= 1:
            multiplier *= 0.82
        elif generic_title_hits >= 1:
            multiplier *= 0.55

    return max(0.80, min(multiplier, 1.10))


def enrich_config_with_profile_rules(
    cfg: dict,
    *,
    resume_text: str,
    profile_roles: Iterable[str] | None,
) -> dict:
    ranking = dict(cfg.get("ranking", {}))
    archetypes = infer_profile_archetypes(resume_text, profile_roles, cfg)
    ranking["profile_archetypes"] = archetypes

    # If the user has stored explicit overrides, use them instead of auto-generating.
    user_override = ranking.get("profile_title_rules_override")
    if user_override and isinstance(user_override, dict):
        ranking["profile_title_rules"] = {
            "strong": list(user_override.get("strong", [])),
            "adjacent": list(user_override.get("adjacent", [])),
            "hybrid": list(user_override.get("hybrid", [])),
        }
    else:
        ranking["profile_title_rules"] = build_profile_title_rules(archetypes)

    ranking["profile_positive_terms"] = build_profile_positive_terms(archetypes)
    out = dict(cfg)
    profile_intent = dict(out.get("profile_intent") or {})
    refined_roles = refine_profile_roles_for_ranking(
        profile_intent.get("roles") or profile_roles,
        resume_text=resume_text,
        archetypes=archetypes,
    )
    if refined_roles:
        profile_intent["roles"] = refined_roles

    if "network_automation_engineer" in archetypes:
        profile_intent["preset"] = "platform_devops"
        ranking["title_relevance_floor"] = max(float(ranking.get("title_relevance_floor", 0.25)), 0.18)
        title_blocklist = set(ranking.get("title_blocklist", []))
        title_blocklist.update(
            {
                "ai engineer",
                "machine learning",
                "llm",
                "genai",
                "software engineer",
                "backend engineer",
                "platform engineer",
                "site reliability",
                "sre",
                "devops",
                "security engineer",
            }
        )
        ranking["title_blocklist"] = sorted(title_blocklist)
        thresholds = dict(ranking.get("role_semantic_thresholds", {}))
        thresholds["platform_devops"] = min(float(thresholds.get("platform_devops", 0.35)), 0.20)
        ranking["role_semantic_thresholds"] = thresholds
        rule_cfg = dict(ranking.get("profile_title_rule_scoring", {}))
        adjacent_cfg = dict(rule_cfg.get("adjacent", {}))
        adjacent_cfg["semantic_floor"] = min(float(adjacent_cfg.get("semantic_floor", 0.50)), 0.35)
        adjacent_cfg["min_skill_overlap"] = min(int(adjacent_cfg.get("min_skill_overlap", 2)), 1)
        hybrid_cfg = dict(rule_cfg.get("hybrid", {}))
        hybrid_cfg["semantic_floor"] = min(float(hybrid_cfg.get("semantic_floor", 0.52)), 0.35)
        hybrid_cfg["min_skill_overlap"] = min(int(hybrid_cfg.get("min_skill_overlap", 3)), 1)
        strong_cfg = dict(rule_cfg.get("strong", {}))
        strong_cfg["multiplier"] = min(float(strong_cfg.get("multiplier", 0.72)), 0.66)
        rule_cfg["adjacent"] = adjacent_cfg
        rule_cfg["hybrid"] = hybrid_cfg
        rule_cfg["strong"] = strong_cfg
        ranking["profile_title_rule_scoring"] = rule_cfg

    if "sap_sd" in archetypes:
        ranking["title_relevance_floor"] = min(float(ranking.get("title_relevance_floor", 0.25)), 0.0)
        thresholds = dict(ranking.get("role_semantic_thresholds", {}))
        thresholds["software_general"] = min(float(thresholds.get("software_general", 0.40)), 0.20)
        ranking["role_semantic_thresholds"] = thresholds

    out["profile_intent"] = profile_intent
    out["ranking"] = ranking
    return out


def title_rule_flags(title: str, cfg: dict) -> dict[str, bool]:
    rules = (cfg.get("ranking", {}) or {}).get("profile_title_rules", {})
    title = (title or "").lower()

    def matches(patterns: list[str]) -> bool:
        return any(re.search(p, title, re.IGNORECASE) for p in patterns)

    return {
        "strong": matches(rules.get("strong", [])),
        "adjacent": matches(rules.get("adjacent", [])),
        "hybrid": matches(rules.get("hybrid", [])),
    }


def text_matches_profile_positive_terms(text: str, cfg: dict) -> bool:
    positive_terms = (cfg.get("ranking", {}) or {}).get("profile_positive_terms", {})
    if not positive_terms:
        return True

    lowered = (text or "").lower()

    # Backward-compatible: flat list → treat all terms as core
    if isinstance(positive_terms, list):
        return _has_any(lowered, positive_terms)

    core = positive_terms.get("core", [])
    broad = positive_terms.get("broad", [])

    if not core and not broad:
        return True

    core_match = _has_any(lowered, core) if core else False
    broad_match = _has_any(lowered, broad) if broad else False

    # Pass if: at least one core term matches, OR (no core terms defined and broad matches)
    if core:
        return core_match
    return broad_match
