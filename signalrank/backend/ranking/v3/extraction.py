from __future__ import annotations

import re
from datetime import datetime

from ranking.v3.lanes import detect_active_lanes
from ranking.v3.profile import ProfileV3, WeightedSkill


_SKILL_PATTERNS = re.compile(
    r"\b(python|java|pytorch|tensorflow|transformers|llm|gpt|bert|spark|kafka|"
    r"sql|postgres|mongodb|redis|docker|kubernetes|ansible|terraform|cisco|bgp|"
    r"ospf|juniper|firewall|sdn|nfv|iot|embedded|mqtt|arduino|rasa|dialogflow|"
    r"spring\s*boot|fastapi|react|typescript|golang|rust|c\+\+|scala|airflow|"
    r"mlflow|sagemaker|azure|aws|gcp|cobol|fortran|hadoop|hive)\b",
    re.IGNORECASE,
)

_DATE_PATTERN = re.compile(
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(\d{4})"
    r"\s*[–\-—to]+\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})|present|current|now|(\d{4}))",
    re.IGNORECASE,
)

_SENIORITY_BANDS = [
    (["principal", "distinguished", "architect", "head of"], "principal"),
    (["staff", "lead", "manager", "director", "vp", "vice president"], "senior"),
    (["senior", "sr.", "sr "], "senior"),
    (["junior", "entry", "associate", "intern"], "junior"),
]


def _current_year() -> int:
    return datetime.now().year


def parse_role_dates(resume_text: str) -> list[dict]:
    """Extract role blocks with their date range and skills."""
    lines = resume_text.splitlines()
    roles: list[dict] = []
    current_role: dict | None = None
    current_year = _current_year()

    for line in lines:
        date_match = _DATE_PATTERN.search(line)
        if date_match:
            start_year = int(date_match.group(1))
            end_str = date_match.group(2).lower().strip()
            if any(w in end_str for w in ("present", "current", "now")):
                end_year = current_year
            elif date_match.group(3):
                end_year = int(date_match.group(3))
            elif date_match.group(4):
                end_year = int(date_match.group(4))
            else:
                end_year = current_year
            current_role = {"start_year": start_year, "end_year": end_year, "skills": [], "text": line}
            roles.append(current_role)
        elif current_role is not None:
            skills_found = [m.group(0).lower() for m in _SKILL_PATTERNS.finditer(line)]
            current_role["skills"].extend(skills_found)
            current_role["text"] += " " + line

    return roles


def compute_skill_recency_weights(
    roles: list[dict],
    current_focus: str | None = None,
) -> dict[str, float]:
    """Return skill → recency_weight in [0.0, 1.0]."""
    current_year = _current_year()
    focus_terms = set(re.findall(r"\w+", (current_focus or "").lower()))
    weights: dict[str, float] = {}

    for role in roles:
        age_years = current_year - role["end_year"]
        if age_years <= 1:
            base_weight = 1.0
        elif age_years >= 5:
            base_weight = 0.2
        else:
            base_weight = 1.0 - (age_years - 1) * (0.8 / 4)

        for skill in role["skills"]:
            existing = weights.get(skill, 0.0)
            weights[skill] = max(existing, base_weight)

    if focus_terms:
        for skill in list(weights.keys()):
            if any(ft in skill or skill in ft for ft in focus_terms):
                weights[skill] = 1.0

    return weights


def _infer_seniority(resume_text: str) -> str:
    text = resume_text.lower()
    for keywords, band in _SENIORITY_BANDS:
        if any(kw in text for kw in keywords):
            return band
    return "mid"


def _infer_domains(resume_text: str, weighted_skills: list[WeightedSkill]) -> list[str]:
    text = resume_text.lower()
    domains: list[str] = []
    if any(kw in text for kw in ("machine learning", "pytorch", "llm", "nlp", "ai", "ml")):
        domains.append("AI / ML")
    if any(kw in text for kw in ("firewall", "bgp", "ospf", "cisco", "network")):
        domains.append("Network / Infrastructure Automation")
    if any(kw in text for kw in ("sap", "erp", "s/4hana")):
        domains.append("SAP / ERP")
    if any(kw in text for kw in ("iot", "embedded", "sensors", "edge")):
        domains.append("IoT / Embedded")
    if any(kw in text for kw in ("innovation", "prototyping", "r&d", "labs")):
        domains.append("Innovation / Emerging Tech")
    return domains or ["Software Engineering"]


def _infer_target_roles(resume_text: str, active_lanes: list[str]) -> list[str]:
    text = resume_text.lower()
    roles: list[str] = []
    if "network" in active_lanes:
        roles += ["Network Engineer", "Network Automation Engineer"]
    if "innovation" in active_lanes:
        roles += ["Innovation Lead", "Prototype Engineer", "R&D Engineer"]
    if "iot" in active_lanes:
        roles += ["IoT Engineer", "Embedded Systems Engineer"]
    if "conversational_ai" in active_lanes:
        roles += ["Conversational AI Engineer", "NLP Engineer"]
    if "r_and_d" in active_lanes:
        roles += ["Research Engineer", "Applied Researcher"]
    if not roles:
        if "machine learning" in text or "pytorch" in text:
            roles += ["ML Engineer", "AI Engineer", "AI Platform Engineer"]
        elif "sap" in text:
            roles += ["SAP Functional Consultant", "SAP SD Consultant"]
        else:
            roles += ["Software Engineer"]
    return roles[:5]


def _extract_locations(resume_text: str) -> list[str]:
    locations: list[str] = []
    text_lower = resume_text.lower()
    if "remote" in text_lower:
        locations.append("Remote")
    for city in ("bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai",
                 "new york", "san francisco", "london", "singapore"):
        if city in text_lower:
            locations.append(city.title())
    return locations or ["Remote"]


def extract_profile_v3(
    resume_text: str,
    candidate_name: str = "",
    current_focus: str | None = None,
) -> ProfileV3:
    """Parse resume text into ProfileV3 with recency-weighted skills and active lanes."""
    roles = parse_role_dates(resume_text)
    recency_weights = compute_skill_recency_weights(roles, current_focus=current_focus)

    if not recency_weights:
        for m in _SKILL_PATTERNS.finditer(resume_text):
            skill = m.group(0).lower()
            if skill not in recency_weights:
                recency_weights[skill] = 0.5

    weighted_skills = [
        WeightedSkill(name=skill, weight=weight)
        for skill, weight in sorted(recency_weights.items(), key=lambda x: -x[1])
    ]

    seniority = _infer_seniority(resume_text)
    active_lanes = detect_active_lanes(resume_text, [], current_focus=current_focus)
    target_roles = _infer_target_roles(resume_text, active_lanes)
    active_lanes = detect_active_lanes(resume_text, target_roles, current_focus=current_focus)
    domains = _infer_domains(resume_text, weighted_skills)

    top_skills = [ws.name for ws in weighted_skills if ws.weight >= 0.7]
    must_have = top_skills[:8]

    avoid = ["support engineer", "qa engineer", "entry level", "intern"]
    if "network" in active_lanes:
        avoid += ["full stack developer", "frontend developer"]
    if "innovation" not in active_lanes and "r_and_d" not in active_lanes:
        avoid += ["research intern", "academic researcher"]

    return ProfileV3(
        candidate_name=candidate_name,
        target_roles=target_roles,
        weighted_skills=weighted_skills,
        domains=domains,
        industries=["Technology"],
        seniority_band=seniority,
        preferred_locations=_extract_locations(resume_text),
        must_have_terms=must_have,
        avoid_terms=avoid[:8],
        current_focus=current_focus,
        active_lanes=active_lanes,
        years_of_experience=None,
    )
