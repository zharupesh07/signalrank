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

    return {
        "strong": sorted(set(strong)),
        "adjacent": sorted(set(adjacent)),
        "hybrid": sorted(set(hybrid)),
    }


def enrich_config_with_profile_rules(
    cfg: dict,
    *,
    resume_text: str,
    profile_roles: Iterable[str] | None,
) -> dict:
    ranking = dict(cfg.get("ranking", {}))
    archetypes = infer_profile_archetypes(resume_text, profile_roles, cfg)
    ranking["profile_archetypes"] = archetypes
    ranking["profile_title_rules"] = build_profile_title_rules(archetypes)
    out = dict(cfg)
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
