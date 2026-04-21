from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 50
DEFAULT_ANALYSIS_K = 20
DEFAULT_LOOKBACK_HOURS = 168
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SCRAPE_CACHE_VERSION = 1
SCRAPE_CACHE_DIR = Path(__file__).resolve().parents[1] / "tmp" / "resume_existing_corpus_rank" / "_scrape_cache"
FAST_MODELS = [
    "google/gemma-4-31b-it:free",
    "arcee-ai/trinity-large-preview:free",
    "google/gemma-4-26b-a4b-it:free",
]

STOPWORDS = {
    "the",
    "and",
    "or",
    "to",
    "of",
    "for",
    "in",
    "on",
    "with",
    "a",
    "an",
    "is",
    "are",
    "as",
    "by",
    "be",
    "this",
    "that",
    "from",
    "will",
    "you",
    "your",
    "our",
    "it",
    "at",
    "we",
    "their",
    "they",
    "them",
}

DEFAULT_SCORE_WEIGHTS = {
    "semantic": 42.0,
    "title_relevance": 0.25,
    "skill_hits": 0.16,
    "location": 0.08,
    "recency": 0.05,
    "seniority": 0.10,
    "curated_phrase": 1.75,
    "curated_token": 0.08,
    "primary_role": 4.5,
    "adjacent_role": 2.0,
    "must_skill": 2.25,
    "supporting_skill": 0.8,
    "domain": 1.0,
    "industry": 0.75,
}

ROLE_PHRASES = [
    ("innovation lead", "Innovation Lead"),
    ("innovation and r&d", "Innovation Lead"),
    ("innovation and research", "Innovation Lead"),
    ("r&d lead", "R&D Lead"),
    ("research and development lead", "R&D Lead"),
    ("emerging technologies lead", "Emerging Technologies Lead"),
    ("emerging technology lead", "Emerging Technologies Lead"),
    ("creative technologist", "Creative Technologist"),
    ("technical expert innovation", "Innovation Research Engineer"),
    ("innovation research engineer", "Innovation Research Engineer"),
    ("research engineer", "Research Engineer"),
    ("prototype engineer", "Prototype Engineer"),
    ("prototyping engineer", "Prototype Engineer"),
    ("innovation consultant", "Innovation Consultant"),
    ("r&d consultant", "Innovation Consultant"),
    ("iot specialist", "IoT Specialist"),
    ("iot engineer", "IoT Engineer"),
    ("iot solutions", "IoT Solutions Lead"),
    ("iot lead", "IoT Solutions Lead"),
    ("hardware head", "Hardware Innovation Lead"),
    ("innovation program", "Innovation Program Lead"),
    ("site reliability engineer", "Site Reliability Engineer"),
    ("sre", "Site Reliability Engineer"),
    ("platform engineer", "Platform Engineer"),
    ("devops engineer", "DevOps Engineer"),
    ("cloud engineer", "Cloud Engineer"),
    ("data engineer", "Data Engineer"),
    ("data analyst", "Data Analyst"),
    ("machine learning engineer", "Machine Learning Engineer"),
    ("ml engineer", "Machine Learning Engineer"),
    ("mlops engineer", "MLOps Engineer"),
    ("ai engineer", "AI Engineer"),
    ("software engineer", "Software Engineer"),
    ("backend engineer", "Backend Engineer"),
    ("frontend engineer", "Frontend Engineer"),
    ("full stack engineer", "Full Stack Engineer"),
    ("fullstack engineer", "Full Stack Engineer"),
    ("network automation engineer", "Network Automation Engineer"),
    ("network engineer", "Network Engineer"),
    ("security engineer", "Security Engineer"),
    ("test automation engineer", "Test Automation Engineer"),
    ("qa engineer", "QA Engineer"),
    ("business analyst", "Business Analyst"),
    ("functional consultant", "Functional Consultant"),
    ("consultant", "Consultant"),
    ("product manager", "Product Manager"),
    ("project manager", "Project Manager"),
    ("program manager", "Program Manager"),
    ("engineering manager", "Engineering Manager"),
    ("technical lead", "Technical Lead"),
    ("lead engineer", "Technical Lead"),
    ("architect", "Architect"),
    ("solution architect", "Solution Architect"),
    ("systems engineer", "Systems Engineer"),
    ("operations manager", "Operations Manager"),
    ("operations engineer", "Operations Engineer"),
]

SKILL_ALIASES = [
    ("python", "Python"),
    ("java", "Java"),
    ("javascript", "JavaScript"),
    ("typescript", "TypeScript"),
    ("golang", "Go"),
    ("go ", "Go"),
    ("react", "React"),
    ("node.js", "Node.js"),
    ("nodejs", "Node.js"),
    ("django", "Django"),
    ("flask", "Flask"),
    ("fastapi", "FastAPI"),
    ("sql", "SQL"),
    ("postgres", "PostgreSQL"),
    ("mysql", "MySQL"),
    ("redis", "Redis"),
    ("kafka", "Kafka"),
    ("spark", "Spark"),
    ("airflow", "Airflow"),
    ("docker", "Docker"),
    ("kubernetes", "Kubernetes"),
    ("terraform", "Terraform"),
    ("ansible", "Ansible"),
    ("aws", "AWS"),
    ("azure", "Azure"),
    ("gcp", "GCP"),
    ("linux", "Linux"),
    ("bash", "Bash"),
    ("shell", "Shell"),
    ("git", "Git"),
    ("ci/cd", "CI/CD"),
    ("microservice", "Microservices"),
    ("rest api", "REST API"),
    ("graphql", "GraphQL"),
    ("pytorch", "PyTorch"),
    ("tensorflow", "TensorFlow"),
    ("scikit-learn", "scikit-learn"),
    ("pandas", "Pandas"),
    ("numpy", "NumPy"),
    ("tableau", "Tableau"),
    ("power bi", "Power BI"),
    ("salesforce", "Salesforce"),
    ("iot", "IoT"),
    ("conversational ai", "Conversational AI"),
    ("robotics", "Robotics"),
    ("blockchain", "Blockchain"),
    ("hyperledger", "Hyperledger"),
    ("ar/vr", "AR/VR"),
    ("3d printing", "3D Printing"),
    ("rapid prototyping", "Rapid Prototyping"),
    ("prototype", "Prototyping"),
    ("esp32", "ESP32"),
    ("raspberry pi", "Raspberry Pi"),
    ("arduino", "Arduino"),
    ("mqtt", "MQTT"),
    ("dialogflow", "Dialogflow"),
    ("alexa skills", "Alexa Skills"),
    ("bot framework", "Bot Framework"),
    ("fusion 360", "Fusion 360"),
    ("llm", "LLM"),
    ("genai", "GenAI"),
    ("rag", "RAG"),
]

LOCATION_ALIASES = {
    "bengaluru": "Bangalore",
    "bangalore": "Bangalore",
    "gurugram": "Gurgaon",
    "gurgaon": "Gurgaon",
    "noida": "Noida",
    "hyderabad": "Hyderabad",
    "chennai": "Chennai",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "delhi": "Delhi",
    "remote": "Remote",
    "india": "India",
    "singapore": "Singapore",
    "london": "London",
    "toronto": "Toronto",
    "berlin": "Berlin",
    "amsterdam": "Amsterdam",
    "sydney": "Sydney",
}


@dataclass(frozen=True)
class ApproachSpec:
    name: str
    label: str
    llm_parse: bool
    agentic: bool


APPROACHES = {
    "deterministic_baseline": ApproachSpec("deterministic_baseline", "Deterministic Baseline", False, False),
    "llm_parse_only": ApproachSpec("llm_parse_only", "LLM Parse Only", True, False),
    "agentic_only": ApproachSpec("agentic_only", "Agentic Only", False, True),
    "llm_parse_plus_agentic": ApproachSpec("llm_parse_plus_agentic", "LLM Parse + Agentic", True, True),
}


@dataclass
class JobRecord:
    job_url: str
    title: str
    company: str
    location: str
    site: str
    description: str
    date_posted: str | None = None


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "resume"


def _dedupe_strs(values: list[str] | tuple[str, ...] | None, *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("pypdf is required for PDF extraction") from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _load_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_terms(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9\+/#-]+", text.lower())
    return [token for token in tokens if len(token) > 1 and token not in STOPWORDS]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _canonicalize_location(value: str) -> str:
    cleaned = re.sub(r"[\s,]+", " ", value).strip()
    if not cleaned:
        return ""
    return LOCATION_ALIASES.get(cleaned.lower(), cleaned)


def _token_set(value: str) -> set[str]:
    return {token for token in _extract_terms(value) if token not in STOPWORDS}


def _extract_locations(resume_text: str) -> list[str]:
    lower = resume_text.lower()
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    header_text = "\n".join(lines[:20]).lower()
    explicit_location_lines = [line.lower() for line in lines[:40] if "location" in line.lower() or "address" in line.lower()]
    scored_locations: list[tuple[int, int, str]] = []
    explicit_locations: list[str] = []
    for order, (needle, canonical) in enumerate(LOCATION_ALIASES.items()):
        pattern = rf"\b{re.escape(needle)}\b"
        count = len(re.findall(pattern, lower))
        if count == 0:
            continue
        if any(re.search(pattern, line) for line in explicit_location_lines):
            explicit_locations.append(canonical)
        score = 0
        if re.search(pattern, header_text):
            score += 4
        if canonical in explicit_locations:
            score += 5
        score += 2 if count >= 2 else 1
        scored_locations.append((score, order, canonical))
    scored_locations.sort(key=lambda item: (-item[0], item[1]))
    explicit_locations = _dedupe_strs(explicit_locations, limit=4)
    explicit_specific_locations = [loc for loc in explicit_locations if loc not in {"India", "Remote"}]
    if explicit_specific_locations:
        locations = explicit_specific_locations
    else:
        strong_locations = [canonical for score, _, canonical in scored_locations if score >= 3]
        locations = _dedupe_strs(strong_locations or [canonical for _, _, canonical in scored_locations], limit=4)
    specific_locations = [loc for loc in locations if loc not in {"India", "Remote"}]
    if specific_locations:
        locations = [loc for loc in locations if loc != "India"]
    return locations


def _top_terms(text: str, limit: int = 6) -> list[str]:
    counter = Counter(_extract_terms(text))
    return [term for term, _ in counter.most_common(limit)]


def _build_domains(resume_text: str, skills: list[str]) -> list[dict[str, Any]]:
    candidates = list(dict.fromkeys(_top_terms(resume_text, limit=8) + skills))
    if not candidates:
        candidates = ["General Software"]
    domains: list[dict[str, Any]] = []
    for idx, term in enumerate(candidates[:5]):
        domains.append({
            "name": term.title(),
            "confidence": round(max(0.35, 0.75 - idx * 0.08), 2),
            "evidence": [term],
        })
    return domains


def _build_industries(resume_text: str) -> list[str]:
    terms = _top_terms(resume_text, limit=6)
    return [term.title() for term in terms]


def _extract_phrase_matches(text: str, phrases: list[tuple[str, str]]) -> list[str]:
    lower = text.lower()
    matches: list[str] = []
    for phrase, canonical in phrases:
        if phrase in lower:
            matches.append(canonical)
    return _dedupe_strs(matches)


def _build_alias_index(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    alias_map: dict[str, list[str]] = {}
    for phrase, canonical in pairs:
        alias_map.setdefault(canonical, []).append(phrase)
        alias_map[canonical].append(canonical)
    return {key: _dedupe_strs(values) for key, values in alias_map.items()}


ROLE_ALIAS_INDEX = _build_alias_index(ROLE_PHRASES)
SKILL_ALIAS_INDEX = _build_alias_index(SKILL_ALIASES)

GENERIC_ROLE_TOKENS = {
    "engineer",
    "developer",
    "consultant",
    "lead",
    "senior",
    "principal",
    "staff",
    "architect",
    "manager",
    "technical",
    "software",
    "systems",
    "solution",
}

ROLE_FAMILY_EXPANSIONS = {
    "innovation lead": ["Innovation Lead", "Emerging Technologies Lead", "Innovation Program Lead"],
    "r&d lead": ["R&D Lead", "Innovation Lead", "Prototype Engineer"],
    "emerging technologies lead": ["Emerging Technologies Lead", "Innovation Lead", "Creative Technologist"],
    "creative technologist": ["Creative Technologist", "Innovation Consultant", "Prototype Engineer"],
    "innovation research engineer": ["Innovation Research Engineer", "Research Engineer", "Prototype Engineer"],
    "research engineer": ["Research Engineer", "Innovation Research Engineer", "Prototype Engineer"],
    "prototype engineer": ["Prototype Engineer", "Creative Technologist", "IoT Engineer"],
    "innovation consultant": ["Innovation Consultant", "Innovation Lead", "Creative Technologist"],
    "iot specialist": ["IoT Specialist", "IoT Engineer", "IoT Solutions Lead"],
    "iot engineer": ["IoT Engineer", "IoT Specialist", "IoT Solutions Lead"],
    "iot solutions lead": ["IoT Solutions Lead", "Innovation Lead", "IoT Engineer"],
    "hardware innovation lead": ["Hardware Innovation Lead", "Prototype Engineer", "IoT Solutions Lead"],
    "innovation program lead": ["Innovation Program Lead", "Innovation Lead", "Innovation Consultant"],
    "software engineer": ["Software Engineer", "Senior Software Engineer", "Staff Engineer"],
    "backend engineer": ["Backend Engineer", "Software Engineer", "Senior Software Engineer"],
    "frontend engineer": ["Frontend Engineer", "Software Engineer", "Senior Software Engineer"],
    "full stack engineer": ["Full Stack Engineer", "Software Engineer", "Senior Software Engineer"],
    "platform engineer": ["Platform Engineer", "Software Engineer", "Staff Engineer"],
    "devops engineer": ["DevOps Engineer", "Platform Engineer", "Software Engineer"],
    "cloud engineer": ["Cloud Engineer", "Platform Engineer", "Software Engineer"],
    "data engineer": ["Data Engineer", "Software Engineer", "Staff Engineer"],
    "machine learning engineer": ["Machine Learning Engineer", "AI Engineer", "Software Engineer"],
    "ai engineer": ["AI Engineer", "Machine Learning Engineer", "Software Engineer"],
    "mlops engineer": ["MLOps Engineer", "AI Engineer", "Platform Engineer"],
    "site reliability engineer": ["Site Reliability Engineer", "Platform Engineer", "Software Engineer"],
    "network automation engineer": ["Network Automation Engineer", "Network Engineer", "Software Engineer"],
    "network engineer": ["Network Engineer", "Systems Engineer", "Software Engineer"],
    "security engineer": ["Security Engineer", "Software Engineer", "Staff Engineer"],
    "functional consultant": ["Functional Consultant", "Consultant", "Senior Consultant"],
    "business analyst": ["Business Analyst", "Consultant", "Senior Consultant"],
    "consultant": ["Consultant", "Senior Consultant"],
    "solution architect": ["Solution Architect", "Architect", "Technical Lead"],
    "architect": ["Architect", "Solution Architect", "Technical Lead"],
    "technical lead": ["Technical Lead", "Lead Engineer", "Staff Engineer"],
    "engineering manager": ["Engineering Manager", "Technical Lead", "Staff Engineer"],
}

ENGINEERING_ROLE_MARKERS = {
    "engineer",
    "developer",
    "platform",
    "devops",
    "cloud",
    "backend",
    "frontend",
    "full stack",
    "security",
    "data",
    "machine learning",
    "mlops",
    "ai",
    "network",
    "site reliability",
}

INNOVATION_ROLE_MARKERS = {
    "innovation",
    "research",
    "emerging",
    "creative technologist",
    "prototype",
    "prototyping",
    "iot",
    "hardware",
    "robotics",
    "conversational ai",
}

INNOVATION_SKILL_PRIORITIES = {
    "IoT",
    "Conversational AI",
    "Robotics",
    "Rapid Prototyping",
    "3D Printing",
    "ESP32",
    "Raspberry Pi",
    "Arduino",
    "MQTT",
    "Dialogflow",
    "Alexa Skills",
    "Fusion 360",
    "AR/VR",
    "Blockchain",
}

INNOVATION_CONTEXT_KEYWORDS = [
    "Innovation",
    "R&D",
    "Emerging Technologies",
    "Rapid Prototyping",
    "Hardware",
    "IoT",
    "Conversational AI",
]

INNOVATION_DRIFT_PENALTIES = {
    "application support": 14.0,
    "support engineer": 12.0,
    "technical support": 12.0,
    "customer support": 10.0,
    "qa engineer": 10.0,
    "quality assurance": 10.0,
    "test engineer": 8.0,
    "manual testing": 8.0,
    "full stack": 6.0,
    "fullstack": 6.0,
}


def _infer_years_of_experience(text: str) -> int | None:
    lower = text.lower()
    patterns = [
        r"(\d{1,2})\+?\s+years?(?:\s+of\s+experience)?",
        r"over\s+(\d{1,2})\s+years?(?:\s+of\s+experience)?",
        r"more than\s+(\d{1,2})\s+years?(?:\s+of\s+experience)?",
        r"(\d{1,2})\s+\+\s+years?(?:\s+of\s+experience)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _infer_seniority_band(years: int | None, text: str) -> str:
    lower = text.lower()
    if years is not None:
        if years <= 2:
            return "entry"
        if years <= 5:
            return "mid"
        if years <= 8:
            return "senior"
        if years <= 12:
            return "lead"
        return "principal"
    if any(term in lower for term in ("principal", "staff", "head", "architect", "lead")):
        return "lead"
    if any(term in lower for term in ("senior", "sr.", "sr ")):
        return "senior"
    if any(term in lower for term in ("junior", "jr.", "fresher", "graduate", "intern")):
        return "entry"
    return "mid"


def _infer_role_candidates(resume_text: str, skills: list[str], domains: list[dict[str, Any]], seniority: str) -> list[str]:
    matches = _extract_phrase_matches(resume_text, ROLE_PHRASES)
    innovation_skills = {skill.lower() for skill in skills}
    if matches:
        if "iot" in innovation_skills and not any("iot" in item.lower() for item in matches):
            matches.append("IoT Solutions Lead" if seniority in {"lead", "principal"} else "IoT Engineer")
        if (
            {"rapid prototyping", "3d printing", "robotics"} & innovation_skills
            and not any("prototype" in item.lower() or "creative technologist" in item.lower() for item in matches)
        ):
            matches.append("Creative Technologist")
        return _dedupe_strs(matches, limit=5)
    lowered = resume_text.lower()
    if (
        any(marker in lowered for marker in ("innovation", "emerging technologies", "research", "prototype", "prototyping"))
        or {"iot", "robotics", "3d printing", "rapid prototyping", "conversational ai"} & innovation_skills
    ):
        candidates = [
            "Innovation Lead" if seniority in {"lead", "principal"} else "Innovation Consultant",
            "IoT Solutions Lead" if "iot" in innovation_skills and seniority in {"lead", "principal"} else "IoT Engineer",
            "Creative Technologist",
            "Prototype Engineer",
        ]
        return _dedupe_strs(candidates, limit=5)
    keywords = _dedupe_strs(_top_terms(resume_text, limit=4), limit=3)
    candidates: list[str] = []
    if keywords:
        phrase = " ".join(word.title() for word in keywords[:2])
        candidates.append(f"{phrase} Engineer")
    if skills:
        candidates.append(f"{skills[0]} Specialist")
    if seniority in {"senior", "lead", "principal"}:
        candidates.append(f"Lead {keywords[0].title()} Engineer" if keywords else "Lead Engineer")
    if not candidates:
        candidates.append("Software Engineer")
    return _dedupe_strs(candidates, limit=5)


def _build_negative_terms(seniority: str) -> list[str]:
    negatives = ["Intern", "Junior", "Graduate", "Fresher", "Student", "Support", "Helpdesk"]
    if seniority in {"senior", "lead", "principal"}:
        negatives.extend(["Entry Level", "Trainee", "Apprentice"])
    return _dedupe_strs(negatives, limit=10)


def _build_skills(resume_text: str) -> list[str]:
    lower = resume_text.lower()
    skills: list[str] = []
    for phrase, canonical in SKILL_ALIASES:
        if phrase in lower:
            skills.append(canonical)
    return _dedupe_strs(skills, limit=20)


def _build_target_roles(
    recent_titles: list[str],
    domains: list[dict[str, Any]],
    skills: list[str],
    seniority: str,
) -> list[dict[str, Any]]:
    fallback_roles = _infer_role_candidates(" ".join(recent_titles), skills, domains, seniority)
    roles = _dedupe_strs(recent_titles + fallback_roles, limit=5)
    target_roles: list[dict[str, Any]] = []
    for idx, role in enumerate(roles):
        target_roles.append({
            "title": role,
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": round(max(0.55, 0.95 - idx * 0.08), 2),
            "evidence": [role],
        })
    return target_roles


def _build_archetypes(domains: list[dict[str, Any]], skills: list[str], seniority: str) -> list[dict[str, Any]]:
    archetypes: list[dict[str, Any]] = []
    for idx, domain in enumerate(domains[:4]):
        domain_name = str(domain.get("name") or "General Software")
        evidence = list(domain.get("evidence") or [])
        if skills:
            evidence.append(", ".join(skills[:4]))
        if seniority:
            evidence.append(f"seniority:{seniority}")
        archetypes.append({
            "id": re.sub(r"[^a-z0-9]", "_", domain_name.lower()).strip("_") or "general",
            "label": domain_name,
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": round(max(0.5, 0.95 - idx * 0.07), 2),
            "evidence": evidence[:3],
        })
    if not archetypes:
        archetypes.append({
            "id": "general_software",
            "label": "General Software",
            "priority": "primary",
            "confidence": 0.5,
            "evidence": [],
        })
    return archetypes


def _build_search_queries(profile: dict[str, Any]) -> list[str]:
    roles = _dedupe_strs(
        list(profile.get("suggested_roles") or [])
        + [str(item.get("title") or "") for item in (profile.get("target_roles") or []) if isinstance(item, dict)]
        + list(profile.get("recent_titles") or []),
        limit=5,
    )
    skills = _dedupe_strs(list(profile.get("skills") or []), limit=5)
    domains = _dedupe_strs([str(item.get("name") or "") for item in (profile.get("domains") or []) if isinstance(item, dict)], limit=3)

    queries: list[str] = []
    for role in roles[:3]:
        queries.append(role)
    for role in roles[:2]:
        for skill in skills[:2]:
            queries.append(f"{role} {skill}")
    queries.extend(domains[:2])
    return _dedupe_strs(queries, limit=8)


def _resume_supports_phrase(resume_text: str, phrase: str, alias_index: dict[str, list[str]] | None = None) -> bool:
    normalized_resume = _normalize_text_for_match(resume_text)
    normalized_phrase = _normalize_text_for_match(phrase)
    if not normalized_phrase:
        return False
    aliases = []
    if alias_index:
        aliases.extend(alias_index.get(phrase, []))
        aliases.extend(alias_index.get(phrase.title(), []))
    aliases.append(phrase)
    for alias in _dedupe_strs(aliases):
        normalized_alias = _normalize_text_for_match(alias)
        if normalized_alias and normalized_alias in normalized_resume:
            return True
    phrase_tokens = _token_set(phrase)
    resume_tokens = _token_set(resume_text)
    return bool(phrase_tokens) and len(phrase_tokens & resume_tokens) >= max(1, min(2, len(phrase_tokens)))


def _resume_support_score(resume_text: str, phrase: str, alias_index: dict[str, list[str]] | None = None) -> int:
    normalized_resume = _normalize_text_for_match(resume_text)
    normalized_phrase = _normalize_text_for_match(phrase)
    if not normalized_phrase:
        return 0
    aliases: list[str] = []
    if alias_index:
        aliases.extend(alias_index.get(phrase, []))
        aliases.extend(alias_index.get(phrase.title(), []))
    aliases.append(phrase)
    best = 0
    for alias in _dedupe_strs(aliases):
        normalized_alias = _normalize_text_for_match(alias)
        if normalized_alias and normalized_alias in normalized_resume:
            best = max(best, 3)
    phrase_tokens = {token for token in _token_set(phrase) if token not in GENERIC_ROLE_TOKENS}
    resume_tokens = _token_set(resume_text)
    overlap = len(phrase_tokens & resume_tokens)
    if overlap >= 2:
        best = max(best, 2)
    elif overlap >= 1:
        best = max(best, 1)
    return best


def _expand_role_families(roles: list[str], seniority: str) -> list[str]:
    expanded: list[str] = []
    band = str(seniority or "").lower()
    for role in roles:
        normalized = _normalize_text(role)
        expansions = ROLE_FAMILY_EXPANSIONS.get(normalized, [])
        if not expansions and any(marker in normalized for marker in ENGINEERING_ROLE_MARKERS):
            expansions = ["Software Engineer"]
            if "ai" in normalized or "machine learning" in normalized or "mlops" in normalized:
                expansions.insert(0, "AI Engineer")
        expanded.extend(expansions)
        if any(marker in normalized for marker in ENGINEERING_ROLE_MARKERS):
            if band in {"senior", "lead", "principal"}:
                expanded.append(f"Senior {role}")
            if band in {"lead", "principal"}:
                expanded.append("Staff Engineer")
        elif "consultant" in normalized and band in {"senior", "lead", "principal"}:
            expanded.append("Senior Consultant")
    return _dedupe_strs(expanded, limit=10)


def _is_engineering_role(role: str) -> bool:
    normalized = _normalize_text(role)
    return any(marker in normalized for marker in ENGINEERING_ROLE_MARKERS)


def _should_allow_engineering_broadening(profile: dict[str, Any]) -> bool:
    target_roles = [str(item.get("title") or "") for item in (profile.get("target_roles") or []) if isinstance(item, dict)]
    primary_roles = [str(item.get("title") or "") for item in (profile.get("target_roles") or []) if isinstance(item, dict) and item.get("priority") == "primary"]
    suggested_roles = [str(item) for item in (profile.get("suggested_roles") or []) if str(item).strip()]
    recent_titles = [str(item) for item in (profile.get("recent_titles") or []) if str(item).strip()]
    role_pool = _dedupe_strs(primary_roles + target_roles + suggested_roles + recent_titles, limit=12)
    engineering_roles = [role for role in role_pool if _is_engineering_role(role)]
    if any(_is_engineering_role(role) for role in primary_roles):
        return True
    return len(engineering_roles) >= 2


def _is_innovation_role(role: str) -> bool:
    normalized = _normalize_text(role)
    return any(marker in normalized for marker in INNOVATION_ROLE_MARKERS)


def _prioritize_skills(skills: list[str], roles: list[str]) -> list[str]:
    if not skills:
        return []
    if any(_is_innovation_role(role) for role in roles):
        prioritized = sorted(
            _dedupe_strs(skills, limit=30),
            key=lambda skill: (
                0 if skill in INNOVATION_SKILL_PRIORITIES else 1,
                0 if skill in {"IoT", "Conversational AI", "Rapid Prototyping", "3D Printing", "Robotics"} else 1,
                skill.lower(),
            ),
        )
        return prioritized
    return _dedupe_strs(skills, limit=30)


def _build_keyword_retrieval_queries(signals: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    role_context = _dedupe_strs(
        list(signals.get("primary_roles") or [])
        + list(signals.get("adjacent_roles") or [])
        + list(signals.get("domain_terms") or [])
        + list(plan.get("domain_queries") or []),
        limit=12,
    )
    if not any(_is_innovation_role(value) for value in role_context):
        return []

    skills = _dedupe_strs(
        list(signals.get("must_have_skills") or []) + list(signals.get("supporting_skills") or []),
        limit=12,
    )
    combined_context = _normalize_text_for_match(" ".join(role_context + skills))

    contexts: list[str] = []
    if "innovation" in combined_context:
        contexts.append("Innovation")
    if "r&d" in combined_context or "research" in combined_context:
        contexts.append("R&D")
    if "emerging" in combined_context:
        contexts.append("Emerging Technologies")
    if any(item in combined_context for item in ("prototype", "prototyping", "3d printing")):
        contexts.append("Rapid Prototyping")
    if any(item in combined_context for item in ("hardware", "esp32", "raspberry pi", "arduino")):
        contexts.append("Hardware")
    if "iot" in combined_context or any(item in combined_context for item in ("mqtt", "esp32", "raspberry pi", "arduino")):
        contexts.append("IoT")
    if "conversational ai" in combined_context or any(item in combined_context for item in ("dialogflow", "alexa skills", "bot framework")):
        contexts.append("Conversational AI")
    contexts = _dedupe_strs(contexts + [value for value in INNOVATION_CONTEXT_KEYWORDS if value.lower() in combined_context], limit=6)

    high_signal_skills = [
        skill
        for skill in skills
        if skill in INNOVATION_SKILL_PRIORITIES or skill in {"IoT", "Conversational AI", "Rapid Prototyping", "3D Printing", "Robotics"}
    ]
    high_signal_skills = _dedupe_strs(high_signal_skills, limit=4)
    consultant_lane = any("consultant" in _normalize_text(role) for role in role_context)

    queries: list[str] = []
    queries.extend(contexts[:3])
    for context in contexts[:3]:
        for skill in high_signal_skills[:2]:
            if _normalize_text(context) != _normalize_text(skill):
                queries.append(f"{context} {skill}")
    if consultant_lane:
        for skill in high_signal_skills[:2]:
            queries.append(f"{skill} Consultant")
    return _dedupe_strs(queries, limit=8)


def _evaluate_search_terms(profile: dict[str, Any], queries: list[str]) -> dict[str, Any]:
    signals = dict(profile.get("matching_signals") or {})
    primary_roles = {str(item).lower() for item in (signals.get("primary_roles") or []) if str(item).strip()}
    adjacent_roles = {str(item).lower() for item in (signals.get("adjacent_roles") or []) if str(item).strip()}
    broadened_roles = {str(item).lower() for item in (signals.get("broadened_roles") or []) if str(item).strip()}
    must_skills = {str(item).lower() for item in (signals.get("must_have_skills") or []) if str(item).strip()}
    supporting_skills = {str(item).lower() for item in (signals.get("supporting_skills") or []) if str(item).strip()}

    role_queries = 0
    role_skill_queries = 0
    broad_role_queries = 0
    keyword_queries = 0
    for query in queries:
        lowered = query.lower()
        has_role = any(role in lowered for role in primary_roles | adjacent_roles | broadened_roles)
        has_skill = any(skill in lowered for skill in must_skills | supporting_skills)
        if has_role and has_skill:
            role_skill_queries += 1
        elif has_role:
            role_queries += 1
        elif has_skill:
            keyword_queries += 1
        if query not in set(signals.get("primary_roles") or []) and query not in set(signals.get("adjacent_roles") or []):
            broad_role_queries += 1

    return {
        "total_queries": len(queries),
        "role_queries": role_queries,
        "role_skill_queries": role_skill_queries,
        "broad_role_queries": broad_role_queries,
        "keyword_queries": keyword_queries,
    }


def _filter_llm_hints(hints: dict[str, Any], resume_text: str) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    filtered["role_phrases"] = [
        item
        for item in (hints.get("role_phrases") or [])
        if _resume_support_score(resume_text, str(item), ROLE_ALIAS_INDEX) >= 2
    ]
    filtered["skill_highlights"] = [
        item
        for item in (hints.get("skill_highlights") or [])
        if _resume_support_score(resume_text, str(item), SKILL_ALIAS_INDEX) >= 2
    ]
    filtered["domain_labels"] = [
        item
        for item in (hints.get("domain_labels") or [])
        if _resume_support_score(resume_text, str(item)) >= 2
    ]
    filtered["industry_labels"] = [
        item
        for item in (hints.get("industry_labels") or [])
        if _resume_support_score(resume_text, str(item)) >= 2
    ]
    filtered["search_queries"] = [
        item
        for item in (hints.get("search_queries") or [])
        if len((_token_set(str(item)) - GENERIC_ROLE_TOKENS) & _token_set(resume_text)) >= 2
    ]
    filtered["negative_keywords"] = _dedupe_strs(hints.get("negative_keywords") or [], limit=8)
    return filtered


def _build_matching_signals(profile: dict[str, Any]) -> dict[str, Any]:
    target_roles = [item for item in (profile.get("target_roles") or []) if isinstance(item, dict)]
    primary_roles = [str(item.get("title") or "") for item in target_roles if item.get("priority") == "primary"]
    adjacent_roles = [str(item.get("title") or "") for item in target_roles if item.get("priority") != "primary"]
    if not primary_roles:
        primary_roles = _dedupe_strs(list(profile.get("suggested_roles") or []), limit=2)
    supporting_roles = _dedupe_strs(adjacent_roles + list(profile.get("recent_titles") or []), limit=4)
    broadened_roles = []
    if _should_allow_engineering_broadening(profile):
        broadened_roles = _expand_role_families(primary_roles + supporting_roles, str(profile.get("seniority_band") or "mid"))
    else:
        broadened_roles = _expand_role_families(primary_roles, str(profile.get("seniority_band") or "mid"))
    role_context = _dedupe_strs(primary_roles + supporting_roles + broadened_roles, limit=12)
    skills = _prioritize_skills(_dedupe_strs(list(profile.get("skills") or []), limit=20), role_context)
    prioritized_must_have_terms = _prioritize_skills(_dedupe_strs(list(profile.get("must_have_terms") or []), limit=20), role_context)
    must_have_skills = _dedupe_strs(prioritized_must_have_terms + skills[:6], limit=8)
    supporting_skills = [skill for skill in skills if skill not in set(must_have_skills)][:8]
    domains = _dedupe_strs([str(item.get("name") or "") for item in (profile.get("domains") or []) if isinstance(item, dict)], limit=5)
    industries = _dedupe_strs(list(profile.get("industries") or []), limit=5)
    locations = _dedupe_strs(list(profile.get("suggested_locations") or []), limit=4)
    exclusions = _dedupe_strs(list(profile.get("avoid_terms") or profile.get("suggested_exclusions") or []), limit=10)
    curated_queries = _dedupe_strs(list(profile.get("curated_queries") or []), limit=12)
    return {
        "primary_roles": primary_roles,
        "adjacent_roles": supporting_roles,
        "broadened_roles": broadened_roles,
        "must_have_skills": must_have_skills,
        "supporting_skills": supporting_skills,
        "domain_terms": domains,
        "industry_terms": industries,
        "preferred_locations": locations,
        "avoid_terms": exclusions,
        "curated_queries": curated_queries,
        "seniority_band": str(profile.get("seniority_band") or "mid"),
        "weights": dict(DEFAULT_SCORE_WEIGHTS),
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return {}
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        data = json.loads(cleaned)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_verification_band(value: str | None) -> str:
    band = str(value or "").strip().lower()
    if band in {"strong_fit", "weak_fit", "reject"}:
        return band
    return "weak_fit"


def _normalize_confidence_band(value: str | None) -> str:
    band = str(value or "").strip().lower()
    if band in {"high", "medium", "low"}:
        return band
    return "medium"


def _normalize_text_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", _normalize_text(value))


def _normalize_verification_results(raw: Any, top_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        items = raw.get("verifications") or raw.get("results") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    by_url = {
        str(item.get("job_url") or ""): item
        for item in items
        if isinstance(item, dict) and str(item.get("job_url") or "").strip()
    }
    normalized: list[dict[str, Any]] = []
    for job in top_jobs:
        url = str(job.get("job_url") or "")
        item = by_url.get(url, {})
        normalized.append({
            "job_url": url,
            "title": job.get("title"),
            "company": job.get("company"),
            "fit_band": _normalize_verification_band(item.get("fit_band")),
            "confidence_band": _normalize_confidence_band(item.get("confidence")),
            "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [str(item.get("evidence") or "").strip()] if item.get("evidence") else [],
        })
    return normalized


def _dedupe_with_audit(candidates: list[str], *, limit: int | None = None) -> tuple[list[str], dict[str, list[str]]]:
    seen: set[str] = set()
    kept: list[str] = []
    duplicates: list[str] = []

    for candidate in candidates:
        item = str(candidate or "").strip()
        key = item.lower()
        if not item:
            continue
        if key in seen:
            duplicates.append(item)
            continue
        seen.add(key)
        kept.append(item)

    trimmed: list[str] = []
    if limit is not None and len(kept) > limit:
        trimmed = kept[limit:]
        kept = kept[:limit]
    audit = {"duplicates": duplicates, "trimmed": trimmed}
    return kept, audit


def _build_deterministic_queries(profile: dict[str, Any], *, max_terms: int = 12) -> tuple[list[str], dict[str, list[str]]]:
    plan = profile.get("query_plan") or {}
    signals = dict(profile.get("matching_signals") or _build_matching_signals(profile))
    title_queries = _dedupe_strs(list(plan.get("title_queries") or []), limit=6)
    must_skills = _dedupe_strs(list(signals.get("must_have_skills") or []) + list(plan.get("skill_queries") or []), limit=4)
    primary_roles = _dedupe_strs(list(signals.get("primary_roles") or []), limit=2)
    adjacent_roles = _dedupe_strs(list(signals.get("adjacent_roles") or []), limit=3)
    broadened_roles = [
        role
        for role in _dedupe_strs(list(signals.get("broadened_roles") or []), limit=8)
        if role not in set(primary_roles) and role not in set(adjacent_roles)
    ]
    domain_queries = _dedupe_strs(list(plan.get("domain_queries") or []), limit=2)
    llm_queries = _dedupe_strs(list(plan.get("search_queries") or []), limit=4)
    keyword_queries = _build_keyword_retrieval_queries(signals, plan)

    core_candidates: list[str] = []
    for role in _dedupe_strs(primary_roles + title_queries, limit=3):
        core_candidates.append(role)
    for role in _dedupe_strs(primary_roles + adjacent_roles, limit=3):
        for skill in must_skills[:2]:
            core_candidates.append(f"{role} {skill}")

    adjacent_candidates: list[str] = []
    for role in adjacent_roles[:2]:
        adjacent_candidates.append(role)
    for role in adjacent_roles[:2]:
        for skill in must_skills[:2]:
            adjacent_candidates.append(f"{role} {skill}")

    exploratory_candidates: list[str] = []
    for role in broadened_roles[:3]:
        for skill in must_skills[:2]:
            exploratory_candidates.append(f"{role} {skill}")
    exploratory_candidates.extend(llm_queries[:2])
    exploratory_candidates.extend(domain_queries[:1])
    exploratory_candidates.extend(keyword_queries[:4])

    candidates = core_candidates + adjacent_candidates + exploratory_candidates
    if not candidates:
        candidates.extend(profile.get("suggested_roles") or [])
        candidates.extend(profile.get("skills") or [])

    queries, audit = _dedupe_with_audit(candidates, limit=max_terms)
    if must_skills:
        role_skill_count = sum(
            1
            for query in queries
            if any(role.lower() in query.lower() for role in primary_roles + adjacent_roles + broadened_roles)
            and any(skill.lower() in query.lower() for skill in must_skills)
        )
        if role_skill_count < 4:
            supplemental: list[str] = []
            for role in _dedupe_strs(primary_roles + adjacent_roles + broadened_roles, limit=6):
                for skill in must_skills[:3]:
                    candidate = f"{role} {skill}"
                    if candidate not in queries:
                        supplemental.append(candidate)
            combined, refill_audit = _dedupe_with_audit(queries + supplemental, limit=max_terms)
            queries = combined
            audit["duplicates"].extend(refill_audit["duplicates"])
            audit["trimmed"].extend(refill_audit["trimmed"])
    audit["evaluation"] = _evaluate_search_terms(profile, queries)
    audit["tiers"] = {
        "core": _dedupe_strs(core_candidates, limit=12),
        "adjacent": _dedupe_strs(adjacent_candidates, limit=12),
        "exploratory": _dedupe_strs(exploratory_candidates, limit=12),
        "keyword": _dedupe_strs(keyword_queries, limit=12),
    }
    logger.debug("Deterministic query audit: %s", audit)
    plan["audit"] = audit
    plan["curated_queries"] = queries
    profile["query_plan"] = plan
    profile["curated_queries"] = queries
    return queries, audit


def _extract_generic_profile(resume_text: str, resume_name: str = "") -> dict[str, Any]:
    skills = _build_skills(resume_text)
    locations = _extract_locations(resume_text)
    domains = _build_domains(resume_text, skills)
    industries = _build_industries(resume_text)
    years = _infer_years_of_experience(resume_text)
    seniority = _infer_seniority_band(years, resume_text)

    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    recent_titles = _dedupe_strs(
        _extract_phrase_matches(resume_text, ROLE_PHRASES)
        + [line for line in lines if len(line.split()) <= 8 and any(term in line.lower() for term, _ in ROLE_PHRASES)],
        limit=3,
    )
    if not recent_titles:
        recent_titles = _infer_role_candidates(resume_text, skills, domains, seniority)[:3]

    suggested_roles = _dedupe_strs(recent_titles + _infer_role_candidates(resume_text, skills, domains, seniority), limit=5)
    if not suggested_roles:
        suggested_roles = ["Software Engineer"]

    target_roles = _build_target_roles(recent_titles or suggested_roles[:2], domains, skills, seniority)
    query_plan = {
        "title_queries": _dedupe_strs(suggested_roles + recent_titles, limit=5),
        "skill_queries": _dedupe_strs(skills, limit=5),
        "domain_queries": _dedupe_strs([str(item.get("name") or "") for item in domains if isinstance(item, dict)], limit=5),
        "negative_keywords": _build_negative_terms(seniority),
        }

    profile = {
        "candidate_name": resume_name or "",
        "candidate_summary": f"{seniority.title()} candidate targeting {', '.join(suggested_roles[:3])}",
        "suggested_roles": suggested_roles,
        "recent_titles": recent_titles[:3],
        "skills": skills[:15],
        "suggested_locations": locations,
        "career_archetypes": _build_archetypes(domains, skills, seniority),
        "suggested_exclusions": query_plan["negative_keywords"][:6],
        "suggested_search_queries": _build_search_queries({
            "suggested_roles": suggested_roles,
            "target_roles": target_roles,
            "recent_titles": recent_titles,
            "skills": skills,
            "domains": domains,
        }),
        "target_roles": target_roles,
        "domains": domains,
        "industries": industries,
        "years_of_experience": years,
        "seniority_band": seniority,
        "must_have_terms": skills[:10],
        "avoid_terms": query_plan["negative_keywords"][:8],
        "query_plan": query_plan,
    }
    profile["matching_signals"] = _build_matching_signals(profile)
    return profile


async def _llm_parse_resume(resume_text: str, client: httpx.AsyncClient, model_hint: str) -> dict[str, Any]:
    system = "Return compact JSON only. You are extracting a resume profile."
    user = f"""Parse this resume into JSON with keys: suggested_roles, recent_titles, skills, suggested_locations, career_archetypes, suggested_exclusions, suggested_search_queries, target_roles, domains, industries, years_of_experience, seniority_band, query_plan.\n\nResume:\n{resume_text[:12000]}"""
    payload = {
        "model": model_hint,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 1200,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    resp = await client.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
            "HTTP-Referer": "https://signalrank.app",
            "X-Title": "SignalRank",
        },
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    try:
        return json.loads(content)
    except Exception:
        return {}


async def _llm_suggest_terms(resume_text: str, client: httpx.AsyncClient, model_hint: str) -> dict[str, Any]:
    system = "You are helping craft deterministic query signals. Return JSON only."
    user = f"""Given this resume text, output JSON with keys role_phrases, domain_labels, industry_labels, skill_highlights, search_queries, negative_keywords.
Return at most 6 entries per list.

Resume:
{resume_text[:12000]}"""
    payload = {
        "model": model_hint,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 800,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    resp = await client.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
            "HTTP-Referer": "https://signalrank.app",
            "X-Title": "SignalRank",
        },
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    try:
        return json.loads(content)
    except Exception:
        return {}


def _merge_list(base: list[str] | None, additions: list[str] | None, *, limit: int | None = None) -> list[str]:
    result = list(base or [])
    seen = {item.lower() for item in result}
    for entry in additions or []:
        text = str(entry or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        result.append(text)
        seen.add(key)
        if limit is not None and len(result) >= limit:
            break
    return result


def _apply_llm_suggestions(profile: dict[str, Any], hints: dict[str, Any]) -> dict[str, Any]:
    updated = dict(profile)
    updated["suggested_roles"] = _merge_list(updated.get("suggested_roles"), hints.get("role_phrases"), limit=6)
    updated["skills"] = _merge_list(updated.get("skills"), hints.get("skill_highlights"), limit=20)
    llm_domains = hints.get("domain_labels", [])
    if llm_domains:
        updated["domains"] = [
            {"name": item, "confidence": 0.7, "evidence": [item]}
            for item in llm_domains
        ]
    updated["industries"] = _merge_list(updated.get("industries"), hints.get("industry_labels"), limit=5)
    query_plan = dict(updated.get("query_plan") or {})
    query_plan["title_queries"] = _merge_list(query_plan.get("title_queries"), hints.get("role_phrases"), limit=6)
    query_plan["skill_queries"] = _merge_list(query_plan.get("skill_queries"), hints.get("skill_highlights"), limit=6)
    query_plan["domain_queries"] = _merge_list(query_plan.get("domain_queries"), hints.get("domain_labels"), limit=5)
    query_plan["negative_keywords"] = _merge_list(query_plan.get("negative_keywords"), hints.get("negative_keywords"), limit=8)
    query_plan["search_queries"] = _merge_list(query_plan.get("search_queries"), hints.get("search_queries"), limit=8)
    updated["query_plan"] = query_plan
    updated["suggested_search_queries"] = _merge_list(updated.get("suggested_search_queries"), query_plan.get("search_queries"), limit=8)
    updated["matching_signals"] = _build_matching_signals(updated)
    return updated


async def _enrich_profile_with_llm(profile: dict[str, Any], resume_text: str) -> dict[str, Any]:
    if not os.environ.get("OPENROUTER_API_KEY"):
        return profile
    try:
        async with httpx.AsyncClient() as client:
            hints = await _llm_suggest_terms(resume_text, client, FAST_MODELS[0])
    except Exception:
        return profile
    return _apply_llm_suggestions(profile, _filter_llm_hints(hints, resume_text))


async def _enrich_profile_with_llm_with_client(
    profile: dict[str, Any],
    resume_text: str,
    client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    if not os.environ.get("OPENROUTER_API_KEY") or client is None:
        return profile
    try:
        hints = await _llm_suggest_terms(resume_text, client, FAST_MODELS[0])
    except Exception:
        return profile
    return _apply_llm_suggestions(profile, _filter_llm_hints(hints, resume_text))


@asynccontextmanager
async def _null_async_client():
    yield None


async def _llm_verify_top_jobs(
    top_jobs: list[dict[str, Any]],
    resume_text: str,
    model_hint: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    if not top_jobs or not os.environ.get("OPENROUTER_API_KEY"):
        return []
    brief_jobs = []
    for job in top_jobs:
        brief_jobs.append({
            "job_url": job.get("job_url"),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "description": (job.get("description") or "")[:1200],
        })
    system = "You are verifying how well each job matches the resume. Return JSON object only."
    user = f"""Resume text:
{resume_text[:6000]}

Jobs:
{json.dumps(brief_jobs, indent=2)}

Return JSON with key verifications containing a list of objects.
Each object must have job_url, fit_band (strong_fit/weak_fit/reject), confidence (high/medium/low), and evidence (1-2 sentences)."""
    payload = {
        "model": model_hint,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": 1200,
        "temperature": 0.0,
    }
    try:
        if client is None:
            async with httpx.AsyncClient() as owned_client:
                resp = await owned_client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
                        "HTTP-Referer": "https://signalrank.app",
                        "X-Title": "SignalRank",
                    },
                    json=payload,
                    timeout=90,
                )
        else:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
                    "HTTP-Referer": "https://signalrank.app",
                    "X-Title": "SignalRank",
                },
                json=payload,
                timeout=90,
            )
        resp.raise_for_status()
    except Exception:
        return []
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "[]")
    try:
        return _normalize_verification_results(_extract_json_object(content), top_jobs)
    except Exception:
        return []


def _collect_unique_jobs_for_verification(
    scored_by_approach: list[tuple[ApproachSpec, list[dict[str, Any]]]],
    limit: int,
) -> list[dict[str, Any]]:
    unique_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for _, scored in scored_by_approach:
        for job in scored[:limit]:
            url = str(job.get("job_url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            unique_jobs.append(job)
    return unique_jobs


def _job_vector(job: JobRecord) -> Counter:
    return Counter(_extract_terms(f"{job.title} {job.description} {job.company} {job.location}"))


def _parse_date_posted(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _derive_recency_score(date_posted: str | None) -> float:
    posted = _parse_date_posted(date_posted)
    if not posted:
        return 70.0
    age_hours = max((datetime.now(timezone.utc) - posted).total_seconds() / 3600.0, 0.0)
    return max(20.0, 100.0 - age_hours / 24.0)


def _infer_job_seniority(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(term in text for term in ("principal", "staff", "head", "architect", "lead")):
        return "lead"
    if any(term in text for term in ("senior", "sr.", "sr ")):
        return "senior"
    if any(term in text for term in ("junior", "jr.", "entry", "associate", "intern")):
        return "entry"
    return "mid"


def _score_seniority_match(profile_band: str, job_band: str) -> float:
    order = {"entry": 0, "mid": 1, "senior": 2, "lead": 3, "principal": 4}
    diff = order.get(job_band, 1) - order.get(profile_band, 1)
    if diff == 0:
        return 1.0
    if diff == -1:
        return 0.9
    if diff == 1:
        return 0.95
    if diff <= -2:
        return 0.6
    return 0.75


def _score_jobs(resume_profile: dict[str, Any], jobs: list[JobRecord], *, agentic: bool) -> list[dict[str, Any]]:
    signals = dict(resume_profile.get("matching_signals") or _build_matching_signals(resume_profile))
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    weights.update(signals.get("weights") or {})
    profile_terms = Counter(
        _extract_terms(" ".join(
            list(resume_profile.get("suggested_roles") or [])
            + list(resume_profile.get("recent_titles") or [])
            + list(resume_profile.get("skills") or [])
            + list(resume_profile.get("suggested_exclusions") or [])
            + [str(item.get("name") or "") for item in (resume_profile.get("domains") or []) if isinstance(item, dict)]
            + list(resume_profile.get("industries") or [])
        ))
    )
    job_vecs = [_job_vector(job) for job in jobs]

    all_terms = sorted(set(profile_terms) | {term for vec in job_vecs for term in vec})
    if not all_terms:
        return []
    idx = {term: i for i, term in enumerate(all_terms)}

    profile_arr = np.zeros(len(all_terms), dtype=np.float32)
    for term, count in profile_terms.items():
        profile_arr[idx[term]] = float(count)

    job_arr = np.zeros((len(job_vecs), len(all_terms)), dtype=np.float32)
    for i, vec in enumerate(job_vecs):
        for term, count in vec.items():
            if term in idx:
                job_arr[i, idx[term]] = float(count)

    dot = job_arr @ profile_arr
    job_norm = np.linalg.norm(job_arr, axis=1) + 1e-6
    profile_norm = float(np.linalg.norm(profile_arr) + 1e-6)
    semantic = dot / (job_norm * profile_norm)

    role_terms = [term for term in _extract_terms(" ".join(signals.get("primary_roles") or signals.get("adjacent_roles") or [])) if term not in STOPWORDS]
    skill_terms = [term for term in _extract_terms(" ".join((signals.get("must_have_skills") or []) + (signals.get("supporting_skills") or []))) if term not in STOPWORDS]
    location_terms = [str(loc).lower() for loc in (signals.get("preferred_locations") or []) if str(loc).strip()]
    avoid_terms = [term.lower() for term in (signals.get("avoid_terms") or []) if str(term).strip()]
    profile_band = str(signals.get("seniority_band") or resume_profile.get("seniority_band") or _infer_seniority_band(resume_profile.get("years_of_experience"), " ".join(resume_profile.get("suggested_roles") or []))).lower()
    curated_terms = [term for term in _extract_terms(" ".join(signals.get("curated_queries") or [])) if term not in STOPWORDS]
    curated_phrases = [
        _normalize_text_for_match(query)
        for query in (signals.get("curated_queries") or [])
        if str(query or "").strip()
    ]
    primary_role_phrases = [_normalize_text_for_match(value) for value in (signals.get("primary_roles") or []) if str(value).strip()]
    adjacent_role_phrases = [_normalize_text_for_match(value) for value in (signals.get("adjacent_roles") or []) if str(value).strip()]
    must_skill_terms = [_normalize_text_for_match(value) for value in (signals.get("must_have_skills") or []) if str(value).strip()]
    supporting_skill_terms = [_normalize_text_for_match(value) for value in (signals.get("supporting_skills") or []) if str(value).strip()]
    domain_terms = [_normalize_text_for_match(value) for value in (signals.get("domain_terms") or []) if str(value).strip()]
    industry_terms = [_normalize_text_for_match(value) for value in (signals.get("industry_terms") or []) if str(value).strip()]
    innovation_profile = any(_is_innovation_role(value) for value in (signals.get("primary_roles") or []) + (signals.get("adjacent_roles") or []))

    scores: list[dict[str, Any]] = []
    for i, job in enumerate(jobs):
        title = _normalize_text(job.title)
        desc = _normalize_text(job.description)
        combined_text = _normalize_text_for_match(f"{job.title} {job.description}")
        title_hits = sum(1 for term in role_terms if term in title)
        skill_hits = sum(1 for term in skill_terms if term in desc)
        overlap_terms = sorted(set(role_terms + skill_terms) & set(_extract_terms(f"{job.title} {job.description}")))
        location_score = 50.0 if not location_terms or any(loc in job.location.lower() for loc in location_terms) else 15.0
        recency_score = _derive_recency_score(job.date_posted)
        title_relevance = min(100.0, 18.0 * title_hits + 7.0 * skill_hits + 4.0 * len(overlap_terms))
        seniority_score = 100.0 * _score_seniority_match(profile_band, _infer_job_seniority(job.title, job.description))
        negative_penalty = sum(8.0 for term in avoid_terms if term and (term in title or term in desc))
        if innovation_profile:
            negative_penalty += sum(
                penalty
                for term, penalty in INNOVATION_DRIFT_PENALTIES.items()
                if term in title or term in desc
            )

        primary_role_hits = sum(1 for phrase in primary_role_phrases if phrase and phrase in combined_text)
        adjacent_role_hits = sum(1 for phrase in adjacent_role_phrases if phrase and phrase in combined_text)
        must_skill_hits = sum(1 for phrase in must_skill_terms if phrase and phrase in combined_text)
        supporting_skill_hits = sum(1 for phrase in supporting_skill_terms if phrase and phrase in combined_text)
        domain_hits = sum(1 for phrase in domain_terms if phrase and phrase in combined_text)
        industry_hits = sum(1 for phrase in industry_terms if phrase and phrase in combined_text)
        curated_token_hits = sum(1 for term in curated_terms if term in title or term in desc)
        curated_phrase_hits = sum(1 for phrase in curated_phrases if phrase and phrase in combined_text)
        base = (
            weights["semantic"] * float(semantic[i])
            + weights["title_relevance"] * title_relevance
            + weights["skill_hits"] * skill_hits
            + weights["location"] * location_score
            + weights["recency"] * recency_score
            + weights["seniority"] * seniority_score
            + weights["curated_phrase"] * curated_phrase_hits
            + weights["curated_token"] * curated_token_hits
            + weights["primary_role"] * primary_role_hits
            + weights["adjacent_role"] * adjacent_role_hits
            + weights["must_skill"] * must_skill_hits
            + weights["supporting_skill"] * supporting_skill_hits
            + weights["domain"] * domain_hits
            + weights["industry"] * industry_hits
            - negative_penalty
        )
        if agentic:
            evidence_hits = len(overlap_terms)
            if evidence_hits >= 6:
                base += 4.0
            elif evidence_hits >= 3:
                base += 1.5
            else:
                base -= 2.5

        fit_band = "strong_fit" if base >= 58 else "weak_fit" if base >= 42 else "reject"
        confidence = "high" if base >= 58 else "medium" if base >= 46 else "low"
        scores.append({
            "rank": i + 1,
            "job_url": job.job_url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "site": job.site,
            "description": job.description,
            "final_score": float(base),
            "semantic_score": float(semantic[i]),
            "title_relevance_score": float(title_relevance),
            "location_score": float(location_score),
            "seniority_score": float(seniority_score),
            "curated_match_score": float(curated_phrase_hits),
            "curated_token_score": float(curated_token_hits),
            "primary_role_score": float(primary_role_hits),
            "adjacent_role_score": float(adjacent_role_hits),
            "must_skill_score": float(must_skill_hits),
            "supporting_skill_score": float(supporting_skill_hits),
            "domain_score": float(domain_hits),
            "industry_score": float(industry_hits),
            "fit_band": fit_band,
            "confidence_band": confidence,
        })

    scores.sort(
        key=lambda item: (
            -item["final_score"],
            -item["curated_match_score"],
            -item["title_relevance_score"],
            str(item["title"]).lower(),
            str(item["company"]).lower(),
            str(item["job_url"]).lower(),
        )
    )
    for idx, item in enumerate(scores, start=1):
        item["rank"] = idx
    return scores


def _build_jobspy_inputs(profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    terms, audit = _build_deterministic_queries(profile, max_terms=10)
    if not terms:
        terms = ["Software Engineer"]
    locations = _dedupe_strs(list(profile.get("suggested_locations") or []), limit=3)
    if not locations:
        locations = ["India"]
    return terms, locations


def _scrape_cache_key(query: dict[str, str], max_results: int) -> str:
    raw = json.dumps(
        {
            "version": SCRAPE_CACHE_VERSION,
            "provider": "jobspy_indeed",
            "term": str(query.get("term") or "").strip().lower(),
            "location": str(query.get("location") or "").strip().lower(),
            "country": str(query.get("country") or "").strip().lower(),
            "max_results": int(max_results),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _scrape_cache_path(cache_key: str) -> Path:
    return SCRAPE_CACHE_DIR / f"{cache_key}.json"


def _jobrecord_to_dict(job: JobRecord) -> dict[str, Any]:
    return {
        "job_url": job.job_url,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "site": job.site,
        "description": job.description,
        "date_posted": job.date_posted,
    }


def _jobrecord_from_dict(payload: dict[str, Any]) -> JobRecord:
    return JobRecord(
        job_url=str(payload.get("job_url") or ""),
        title=str(payload.get("title") or ""),
        company=str(payload.get("company") or ""),
        location=str(payload.get("location") or ""),
        site=str(payload.get("site") or "indeed"),
        description=str(payload.get("description") or ""),
        date_posted=str(payload.get("date_posted") or "") or None,
    )


def _load_scrape_cache(cache_key: str) -> dict[str, Any] | None:
    path = _scrape_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _store_scrape_cache(cache_key: str, payload: dict[str, Any]) -> None:
    SCRAPE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _scrape_cache_path(cache_key).write_text(json.dumps(payload, indent=2) + "\n")


def _merge_job_records(*job_lists: list[JobRecord]) -> list[JobRecord]:
    merged: list[JobRecord] = []
    seen: set[str] = set()
    for jobs in job_lists:
        for job in jobs:
            if not job.job_url or job.job_url in seen:
                continue
            seen.add(job.job_url)
            merged.append(job)
    return merged


async def _scrape_jobspy(
    terms: list[str],
    locations: list[str],
    hours_old: int,
    max_results: int,
) -> tuple[list[JobRecord], list[dict[str, Any]], dict[str, Any]]:
    try:
        from jobspy import scrape_jobs
    except Exception as exc:
        raise RuntimeError("python-jobspy is required") from exc

    queries: list[dict[str, Any]] = [{"term": term, "location": location, "country": "India"} for term in terms for location in locations]
    cache_summary = {
        "full_hits": 0,
        "incremental_hits": 0,
        "misses": 0,
        "queries": [],
    }

    async def _one(query: dict[str, Any]) -> tuple[list[JobRecord], dict[str, Any]]:
        now = datetime.now(timezone.utc)
        cache_key = _scrape_cache_key(query, max_results)
        cached_payload = _load_scrape_cache(cache_key)
        cache_meta = {
            "term": query["term"],
            "location": query["location"],
            "country": query["country"],
            "cache_mode": "miss",
            "fetched_hours": hours_old,
        }

        async def _fetch(hours: int) -> list[JobRecord]:
            hours = max(1, int(hours))
            df = await asyncio.to_thread(
                scrape_jobs,
                site_name=["indeed"],
                search_term=query["term"],
                location=query["location"],
                results_wanted=max_results,
                hours_old=hours,
                country_indeed="India",
            )
            out: list[JobRecord] = []
            for _, row in df.iterrows():
                url = str(row.get("job_url_direct") or row.get("job_url") or "").strip()
                if not url:
                    continue
                out.append(JobRecord(
                    job_url=url,
                    title=str(row.get("title") or ""),
                    company=str(row.get("company") or ""),
                    location=str(row.get("location") or ""),
                    site=str(row.get("site") or "indeed"),
                    description=str(row.get("description") or ""),
                    date_posted=str(row.get("date_posted") or "") or None,
                ))
            return out

        if cached_payload:
            try:
                fetched_at = datetime.fromisoformat(str(cached_payload.get("fetched_at") or "").replace("Z", "+00:00"))
            except Exception:
                fetched_at = None
            cached_hours = int(cached_payload.get("hours_old") or 0)
            cached_jobs = [_jobrecord_from_dict(item) for item in (cached_payload.get("jobs") or []) if isinstance(item, dict)]
            if fetched_at is not None:
                age_hours = max((now - fetched_at).total_seconds() / 3600.0, 0.0)
                if age_hours <= 0.25 and cached_hours == hours_old:
                    cache_meta["cache_mode"] = "full_hit"
                    cache_meta["fetched_hours"] = 0
                    return cached_jobs, cache_meta
                if cached_hours == hours_old and hours_old <= cached_hours + age_hours:
                    incremental_hours = max(1, min(hours_old, int(age_hours + 0.999)))
                    fresh_jobs = await _fetch(incremental_hours)
                    merged_jobs = _merge_job_records(fresh_jobs, cached_jobs)
                    _store_scrape_cache(
                        cache_key,
                        {
                            "fetched_at": now.isoformat(),
                            "hours_old": hours_old,
                            "query": query,
                            "max_results": max_results,
                            "jobs": [_jobrecord_to_dict(job) for job in merged_jobs],
                        },
                    )
                    cache_meta["cache_mode"] = "incremental"
                    cache_meta["fetched_hours"] = incremental_hours
                    return merged_jobs, cache_meta

        jobs = await _fetch(hours_old)
        _store_scrape_cache(
            cache_key,
            {
                "fetched_at": now.isoformat(),
                "hours_old": hours_old,
                "query": query,
                "max_results": max_results,
                "jobs": [_jobrecord_to_dict(job) for job in jobs],
            },
        )
        cache_meta["cache_mode"] = "miss"
        cache_meta["fetched_hours"] = hours_old
        return jobs, cache_meta

    results = await asyncio.gather(*[_one(query) for query in queries])
    jobs: list[JobRecord] = []
    seen: set[str] = set()
    query_results: list[dict[str, Any]] = []
    for query, (batch, meta) in zip(queries, results):
        query_results.append({**query, **meta})
        if meta["cache_mode"] == "full_hit":
            cache_summary["full_hits"] += 1
        elif meta["cache_mode"] == "incremental":
            cache_summary["incremental_hits"] += 1
        else:
            cache_summary["misses"] += 1
        cache_summary["queries"].append({**query, **meta})
        for job in batch:
            if job.job_url in seen:
                continue
            seen.add(job.job_url)
            jobs.append(job)
    return jobs, query_results, cache_summary


def _render_summary(name: str, result: dict[str, Any], analysis_k: int) -> str:
    lines = [
        f"# {name}",
        "",
        f"- ranked_jobs: `{result['ranked_jobs']}`",
        f"- scraped_jobs: `{result['scraped_jobs']}`",
        f"- persisted_job_ids: `{result['persisted_job_ids']}`",
        f"- stage_timings_ms: `{result.get('stage_timings_ms', {})}`",
        f"- scrape_cache: `{result.get('scrape_cache', {})}`",
        "",
    ]
    for app in result["approaches"]:
        lines.append(f"## {app['label']}")
        if not app["success"]:
            lines.append(f"- error: `{app['error']}`")
            continue
        verification = app.get("llm_verification") or []
        if verification:
            label_counts = Counter(item.get("fit_band") for item in verification if item.get("fit_band"))
            lines.append(f"- llm_verification: `{len(verification)}` jobs")
            lines.append("- verification_labels: " + ", ".join(f"{label}={count}" for label, count in sorted(label_counts.items())))
            for item in verification[:min(analysis_k, 5)]:
                evidence = "; ".join(item.get("evidence") or [])
                lines.append(f"- verify {item.get('fit_band')} {item.get('confidence_band')} | {item.get('title')} | {evidence}")
        for job in app["top_jobs"][:analysis_k]:
            lines.append(
                f"- {job['rank']}. {job['title']} | {job['company']} | {job['fit_band']} {job['confidence_band']} | {round(job['final_score'], 2)}"
            )
        lines.append("")
    return "\n".join(lines)


async def _run_for_resume(resume_path: Path, args) -> dict[str, Any]:
    started = time.perf_counter()
    stage_timings_ms: dict[str, float] = {}

    resume_text = _load_resume_text(resume_path)
    stage_timings_ms["load_resume"] = round((time.perf_counter() - started) * 1000, 2)

    parse_started = time.perf_counter()
    base_profile = _extract_generic_profile(resume_text, resume_path.stem)
    stage_timings_ms["deterministic_profile"] = round((time.perf_counter() - parse_started) * 1000, 2)
    llm_enabled = bool(os.environ.get("OPENROUTER_API_KEY"))
    async with httpx.AsyncClient() if llm_enabled else _null_async_client() as llm_client:
        enrich_started = time.perf_counter()
        enriched_profile = await _enrich_profile_with_llm_with_client(base_profile, resume_text, llm_client)
        stage_timings_ms["llm_enrich_profile"] = round((time.perf_counter() - enrich_started) * 1000, 2)
        llm_profile: dict[str, Any] = {}
        if llm_enabled and any(spec.llm_parse for spec in APPROACHES.values()):
            try:
                llm_parse_started = time.perf_counter()
                llm_profile = await _llm_parse_resume(resume_text, llm_client, FAST_MODELS[0])
                stage_timings_ms["llm_parse_profile"] = round((time.perf_counter() - llm_parse_started) * 1000, 2)
            except Exception:
                llm_profile = {}
        if args.scrape_jobspy:
            scrape_started = time.perf_counter()
            terms, locations = _build_jobspy_inputs(enriched_profile)
            jobs, queries, scrape_cache = await _scrape_jobspy(
                args.jobspy_terms or terms,
                args.jobspy_locations or locations,
                args.jobspy_hours_old,
                args.jobspy_max_results_per_query,
            )
            stage_timings_ms["scrape_jobspy"] = round((time.perf_counter() - scrape_started) * 1000, 2)
        else:
            raise RuntimeError("This baseline runner expects --scrape-jobspy")

        report = {
            "resume": str(resume_path),
            "queries": queries,
            "scraped_jobs": len(jobs),
            "persisted_job_ids": len(jobs),
            "approaches": [],
            "ranked_jobs": 0,
            "parsed_profile": enriched_profile,
            "stage_timings_ms": stage_timings_ms,
            "scrape_cache": scrape_cache,
        }

        scored_by_approach: list[tuple[ApproachSpec, dict[str, Any], list[dict[str, Any]]]] = []
        for spec in APPROACHES.values():
            profile = dict(enriched_profile)
            if spec.llm_parse:
                if llm_profile:
                    for key in (
                        "suggested_roles",
                        "recent_titles",
                        "skills",
                        "suggested_locations",
                        "career_archetypes",
                        "suggested_exclusions",
                        "suggested_search_queries",
                        "target_roles",
                        "domains",
                        "industries",
                        "years_of_experience",
                        "seniority_band",
                        "query_plan",
                    ):
                        if llm_profile.get(key):
                            profile[key] = llm_profile[key]
                    profile["matching_signals"] = _build_matching_signals(profile)
                else:
                    profile["llm_fallback"] = True
            rank_started = time.perf_counter()
            scored = _score_jobs(profile, jobs, agentic=spec.agentic)
            stage_timings_ms[f"rank_{spec.name}"] = round((time.perf_counter() - rank_started) * 1000, 2)
            scored_by_approach.append((spec, profile, scored))
            report["ranked_jobs"] = max(report["ranked_jobs"], len(scored))

        verification_by_url: dict[str, dict[str, Any]] = {}
        verification_model = args.llm_verify_model or FAST_MODELS[0]
        if args.llm_verify_top:
            unique_jobs = _collect_unique_jobs_for_verification(
                [(spec, scored) for spec, _, scored in scored_by_approach],
                args.llm_verify_top,
            )
            verify_started = time.perf_counter()
            verification = await _llm_verify_top_jobs(unique_jobs, resume_text, verification_model, llm_client)
            stage_timings_ms["llm_verify_unique_top_jobs"] = round((time.perf_counter() - verify_started) * 1000, 2)
            verification_by_url = {
                str(item.get("job_url") or ""): item
                for item in verification
                if str(item.get("job_url") or "").strip()
            }

        for spec, profile, scored in scored_by_approach:
            llm_verification = [
                verification_by_url[job["job_url"]]
                for job in scored[:args.llm_verify_top]
                if job["job_url"] in verification_by_url
            ]
            report["approaches"].append({
                "approach": spec.name,
                "label": spec.label,
                "success": True,
                "ranked_jobs": len(scored),
                "top_jobs": scored[:args.top_k],
                "llm_fallback": bool(profile.get("llm_fallback")),
                "llm_verification": llm_verification,
            })
        stage_timings_ms["total"] = round((time.perf_counter() - started) * 1000, 2)
        return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone resume ranker baseline with no DB dependency")
    parser.add_argument("--resume", required=True)
    parser.add_argument("--scrape-jobspy", action="store_true")
    parser.add_argument("--jobspy-term", dest="jobspy_terms", action="append")
    parser.add_argument("--jobspy-location", dest="jobspy_locations", action="append")
    parser.add_argument("--jobspy-hours-old", type=int, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--jobspy-max-results-per-query", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--analysis-k", type=int, default=DEFAULT_ANALYSIS_K)
    parser.add_argument("--label")
    parser.add_argument("--output-dir")
    parser.add_argument("--llm-verify-top", type=int, default=0, help="run optional LLM verification on top N ranked jobs")
    parser.add_argument("--llm-verify-model", default=FAST_MODELS[0], help="model for LLM verification")
    return parser


async def main_async() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    resume_path = Path(args.resume).expanduser().resolve()
    if not resume_path.exists():
        raise FileNotFoundError(resume_path)
    report = await _run_for_resume(resume_path, args)
    out_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path(__file__).resolve().parents[1]
        / "tmp"
        / "resume_existing_corpus_rank"
        / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_slugify(args.label or resume_path.stem)}-standalone"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "jobspy_scrape_report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "summary.md").write_text(_render_summary(args.label or resume_path.stem, report, args.analysis_k))
    print(json.dumps({"output_dir": str(out_dir), "scraped_jobs": report["scraped_jobs"], "ranked_jobs": report["ranked_jobs"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main_async())
