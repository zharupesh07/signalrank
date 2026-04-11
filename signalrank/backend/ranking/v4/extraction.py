from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ranking.v4.lanes import LANE_REGISTRY, detect_active_lanes
from ranking.v4.profile import CandidateProfile, WeightedSkill


_SKILL_PATTERNS = re.compile(
    r"\b(python|java|pytorch|tensorflow|transformers|llm|gpt|bert|spark|kafka|"
    r"sql|postgres|mongodb|redis|docker|kubernetes|ansible|terraform|cisco|bgp|"
    r"ospf|juniper|firewall|sdn|nfv|iot|embedded|mqtt|arduino|rasa|dialogflow|"
    r"spring\s*boot|fastapi|react|typescript|golang|rust|c\+\+|scala|airflow|"
    r"mlflow|sagemaker|azure|aws|gcp|cobol|fortran|hadoop|hive|sap|abap|"
    r"s/4hana|otc|gts|fiori|mm|sd|langgraph|langchain|langfuse|chroma|faiss|"
    r"cloud\s*run|jenkins|github\s*actions|oidc|rbac|pydantic|sqlmodel|"
    r"seldon(?:\s*core)?|label\s*studio|openai|gemini|claude|mcp|"
    r"function\s*calling|rag|llmops|genai|agentic(?:\s*ai)?|idp|nbdev)\b",
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

_GENERIC_SPECIALIST_SKILLS = {
    "python", "java", "sql", "postgres", "mongodb", "redis", "docker",
    "kubernetes", "aws", "azure", "gcp", "react", "typescript",
}

_LANE_SKILL_PRIORITIES: dict[str, tuple[str, ...]] = {
    "sap_erp": ("sap", "s/4hana", "sd", "mm", "gts", "otc", "abap", "fiori"),
    "network": ("cisco", "bgp", "ospf", "juniper", "firewall", "sdn", "nfv"),
    "iot": ("iot", "embedded", "mqtt", "arduino", "raspberry pi"),
    "conversational_ai": ("dialogflow", "rasa", "nlp", "llm", "gpt"),
    "innovation": ("prototype", "prototyping", "innovation", "mvp"),
    "r_and_d": ("research", "experimental", "prototype", "poc"),
    "mlops_platform": ("mlflow", "kubeflow", "databricks", "mlops", "llmops", "sagemaker", "airflow", "kubernetes", "terraform", "cloud run", "langgraph"),
}

_NORMALIZED_SKILL_ALIASES: dict[str, str] = {
    "cloud run": "cloud run",
    "github actions": "github actions",
    "internal developer platforms": "internal developer platforms",
    "internal developer platforms (idp)": "internal developer platforms",
    "vector databases": "vector databases",
    "vector databases (chroma/faiss)": "vector databases",
    "function calling": "function calling",
    "model context protocol": "mcp",
    "mcp (model context protocol)": "mcp",
    "generative ai": "genai",
    "agentic systems": "agentic ai",
    "agentic ai": "agentic ai",
    "ci/cd": "cicd",
    "iac": "infrastructure as code",
    "hugging face": "hugging face",
    "openai/gemini/claude apis": "llm apis",
    "langgraph": "langgraph",
    "langchain": "langchain",
    "langfuse": "langfuse",
    "seldon core": "seldon core",
    "label studio": "label studio",
    "mlflow": "mlflow",
    "terraform": "terraform",
    "jenkins": "jenkins",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "gcp": "gcp",
    "aws": "aws",
    "fastapi": "fastapi",
    "python": "python",
}

_ROLE_CANONICAL_ALIASES: dict[str, str] = {
    "senior ai platform engineer": "AI Platform Engineer",
    "ai platform engineer": "AI Platform Engineer",
    "cloud infrastructure": "Cloud Infrastructure Engineer",
    "cloud infrastructure engineer": "Cloud Infrastructure Engineer",
    "machine learning engineer": "Machine Learning Engineer",
    "senior machine learning engineer": "Machine Learning Engineer",
    "ml engineer": "Machine Learning Engineer",
    "mlops": "MLOps Engineer",
    "ml ops": "MLOps Engineer",
    "mlops engineer": "MLOps Engineer",
    "llmops": "LLMOps Engineer",
    "llm ops": "LLMOps Engineer",
    "llmops engineer": "LLMOps Engineer",
    "agentic systems": "Agentic AI Engineer",
    "agentic ai": "Agentic AI Engineer",
    "agentic ai engineer": "Agentic AI Engineer",
    "ml platform engineer": "ML Platform Engineer",
    "platform engineer": "Platform Engineer",
    "cloud ops engineer": "Cloud Ops Engineer",
    "devops sre": "DevOps SRE",
    "devops engineer": "DevOps Engineer",
}

_ROLE_REJECT_TOKENS = ("intern", "trainee", "qa", "support")
_SECONDARY_MUST_HAVE_SKILLS = {"oidc", "rbac", "sqlmodel", "langfuse", "label studio", "jenkins"}

_PREFERRED_COMPANY_TIER_GROUPS: dict[str, list[str]] = {
    "enterprise": ["tier_ss", "tier_s"],
    "product": ["tier_ss", "tier_s", "tier_a"],
    "faang": ["tier_ss", "tier_s", "tier_a"],
    "maang": ["tier_ss", "tier_s", "tier_a"],
}


def _current_year() -> int:
    return datetime.now().year


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_skill_name(skill: str) -> str:
    normalized = re.sub(r"\s+", " ", str(skill or "").strip().lower())
    normalized = normalized.replace("/", " / ")
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,")
    return _NORMALIZED_SKILL_ALIASES.get(normalized, normalized)


def _parse_year(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None


def _load_structured_resume(profile_cfg: dict) -> dict | None:
    inline_payload = profile_cfg.get("structured_resume_json")
    if isinstance(inline_payload, dict):
        return inline_payload

    raw_payload = profile_cfg.get("structured_resume")
    if isinstance(raw_payload, dict):
        return raw_payload

    raw_path = str(profile_cfg.get("structured_resume_json_path") or "").strip()
    if not raw_path:
        return None

    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _structured_resume_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("position", "summary", "location"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for exp in data.get("experiences", []) or []:
        if not isinstance(exp, dict):
            continue
        for key in ("title", "company", "location", "tech"):
            value = exp.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        for bullet in exp.get("bullets", []) or []:
            if isinstance(bullet, str) and bullet.strip():
                parts.append(bullet.strip())
    for group in data.get("skills", []) or []:
        if not isinstance(group, dict):
            continue
        category = group.get("category")
        if isinstance(category, str) and category.strip():
            parts.append(category.strip())
        for item in group.get("items", []) or []:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
    return "\n".join(parts)


def _structured_skill_weights(data: dict) -> dict[str, float]:
    weights: dict[str, float] = {}

    def _bump(skill: str, weight: float) -> None:
        normalized = _normalize_skill_name(skill)
        if not normalized:
            return
        weights[normalized] = max(weights.get(normalized, 0.0), weight)

    for group in data.get("skills", []) or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items", []) or []:
            if isinstance(item, str):
                _bump(item, 1.0)

    for exp in data.get("experiences", []) or []:
        if not isinstance(exp, dict):
            continue
        tech = exp.get("tech")
        if isinstance(tech, str):
            for item in tech.split(","):
                _bump(item, 0.95)
        exp_text = " ".join(
            str(part).strip()
            for part in [exp.get("title"), exp.get("company"), exp.get("location"), *list(exp.get("bullets", []) or [])]
            if str(part or "").strip()
        )
        for match in _SKILL_PATTERNS.finditer(exp_text):
            _bump(match.group(0), 0.9)

    summary_text = _structured_resume_text(data)
    for match in _SKILL_PATTERNS.finditer(summary_text):
        _bump(match.group(0), 0.85)

    return weights


def _structured_target_roles(data: dict) -> list[str]:
    raw_roles: list[str] = []

    position = data.get("position")
    if isinstance(position, str) and position.strip():
        raw_roles.extend(part.strip() for part in position.split("|") if part.strip())

    contains = data.get("position_contains")
    if isinstance(contains, str) and contains.strip():
        raw_roles.append(contains.strip())

    for exp in data.get("experiences", []) or []:
        if isinstance(exp, dict):
            title = exp.get("title")
            if isinstance(title, str) and title.strip():
                raw_roles.append(title.strip())

    for marker in data.get("experience_markers", []) or []:
        if isinstance(marker, dict):
            title = marker.get("title")
            if isinstance(title, str) and title.strip():
                raw_roles.append(title.strip())

    normalized_roles: list[str] = []
    for role in raw_roles:
        compact_role = re.sub(r"\([^)]*\)", "", role).strip(" -")
        key = re.sub(r"\s+", " ", compact_role.lower().strip())
        if not key or any(token in key for token in _ROLE_REJECT_TOKENS):
            continue
        canonical = _ROLE_CANONICAL_ALIASES.get(key)
        if canonical:
            normalized_roles.append(canonical)
            continue
        if not any(term in key for term in ("engineer", "architect", "platform", "mlops", "llmops", "ai", "cloud")):
            continue
        if compact_role:
            normalized_roles.append(compact_role)
    return _dedupe_keep_order(normalized_roles)[:8]


def _structured_locations(data: dict) -> list[str]:
    values: list[str] = []
    location = data.get("location")
    if isinstance(location, str):
        values.extend(part.strip() for part in re.split(r"[,|/]", location) if part.strip())
    for exp in data.get("experiences", []) or []:
        if isinstance(exp, dict):
            loc = exp.get("location")
            if isinstance(loc, str) and loc.strip():
                values.append(loc.strip())
    normalized: list[str] = []
    for value in values:
        lower = value.lower()
        if "bangal" in lower or "bengaluru" in lower:
            normalized.append("Bangalore")
        elif "pune" in lower:
            normalized.append("Pune")
        elif "remote" in lower:
            normalized.append("Remote")
        else:
            normalized.append(value.title())
    return _dedupe_keep_order(normalized)


def _structured_years_of_experience(data: dict) -> int | None:
    current_year = _current_year()
    years: list[int] = []
    for exp in data.get("experiences", []) or []:
        if not isinstance(exp, dict):
            continue
        dates = str(exp.get("dates") or "")
        start_year = _parse_year(dates)
        if start_year is None:
            continue
        end_years = re.findall(r"(19|20)\d{2}", dates)
        if re.search(r"present|current|now", dates, re.IGNORECASE):
            end_year = current_year
        else:
            all_years = re.findall(r"(?:19|20)\d{2}", dates)
            end_year = int(all_years[-1]) if all_years else start_year
        years.append(max(0, end_year - start_year))
    if not years:
        return None
    return max(years) if len(years) == 1 else sum(years)


def _structured_company_preferences(profile_cfg: dict) -> list[str]:
    tiers = [str(item).strip().lower() for item in profile_cfg.get("preferred_company_tiers", []) or [] if str(item).strip()]
    tags = [str(item).strip().lower() for item in profile_cfg.get("preferred_company_themes", []) or [] if str(item).strip()]
    for tag in tags:
        tiers.extend(_PREFERRED_COMPANY_TIER_GROUPS.get(tag, []))
    return _dedupe_keep_order(tiers)


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


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(phrase) + r"\b", text) for phrase in phrases)


def _infer_domains(resume_text: str, weighted_skills: list[WeightedSkill]) -> list[str]:
    text = resume_text.lower()
    domains: list[str] = []
    if _contains_any(text, ("machine learning", "pytorch", "llm", "nlp", "dialogflow", "conversational ai", "gen ai", "generative ai")):
        domains.append("AI / ML")
    if _contains_any(text, ("firewall", "bgp", "ospf", "cisco", "network")):
        domains.append("Network / Infrastructure Automation")
    if _contains_any(text, ("sap", "erp", "s/4hana", "order to cash", "otc")):
        domains.append("SAP / ERP")
    if _contains_any(text, ("iot", "embedded", "sensors", "mqtt", "arduino", "raspberry pi")):
        domains.append("IoT / Embedded")
    if _contains_any(text, ("innovation strategy", "innovation program", "prototyping", "r&d", "research and development", "proof of concepts", "poc")):
        domains.append("Innovation / Emerging Tech")
    return domains or ["Software Engineering"]


def _infer_target_roles(resume_text: str, active_lanes: list[str]) -> list[str]:
    text = resume_text.lower()
    roles: list[str] = []
    if "sap_erp" in active_lanes:
        roles += ["SAP SD Consultant", "SAP Functional Consultant", "SAP OTC Consultant"]
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
    if "mlops_platform" in active_lanes:
        roles += ["MLOps Engineer", "AI Platform Engineer", "ML Infrastructure Engineer"]
    if not roles:
        if "machine learning" in text or "pytorch" in text:
            roles += ["ML Engineer", "AI Engineer", "AI Platform Engineer"]
        elif "sap" in text:
            roles += ["SAP Functional Consultant", "SAP SD Consultant"]
        else:
            roles += ["Software Engineer"]
    seen: set[str] = set()
    deduped: list[str] = []
    for role in roles:
        key = role.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(role)
    return deduped[:6]


def _extract_locations(resume_text: str) -> list[str]:
    locations: list[str] = []
    text_lower = resume_text.lower()
    if "remote" in text_lower:
        locations.append("Remote")
    for city in ("bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune", "chennai",
                 "new york", "san francisco", "london", "singapore"):
        if city in text_lower:
            locations.append("Bangalore" if city == "bengaluru" else city.title())
    return locations or ["Remote"]


def _select_must_have_terms(
    weighted_skills: list[WeightedSkill],
    active_lanes: list[str],
) -> list[str]:
    ordered_skills = [ws.name for ws in weighted_skills]
    selected: list[str] = []

    for lane_name in active_lanes:
        for skill_name in _LANE_SKILL_PRIORITIES.get(lane_name, ()):
            if skill_name in ordered_skills and skill_name not in selected:
                selected.append(skill_name)

    for skill_name in ordered_skills:
        if skill_name in selected or skill_name in _GENERIC_SPECIALIST_SKILLS or skill_name in _SECONDARY_MUST_HAVE_SKILLS:
            continue
        selected.append(skill_name)

    if not selected:
        selected = ordered_skills[:5]

    return selected[:8]


def extract_profile_v4(
    resume_text: str,
    current_focus: str | None = None,
    config_overrides: dict | None = None,
) -> CandidateProfile:
    """Parse resume text into CandidateProfile with recency-weighted skills and active lanes.

    No hardcoded candidate names. Per-user customizations come from config_overrides:
      config_overrides.get("v4_profile", {}).get("must_have_terms")
      config_overrides.get("v4_profile", {}).get("avoid_terms")
      config_overrides.get("v4_profile", {}).get("target_roles")
    """
    profile_cfg = (config_overrides or {}).get("v4_profile", {})
    structured_resume = _load_structured_resume(profile_cfg)
    structured_resume_text = _structured_resume_text(structured_resume) if structured_resume else ""
    combined_resume_text = "\n".join(part for part in [resume_text, structured_resume_text] if part)

    roles = parse_role_dates(combined_resume_text)
    recency_weights = compute_skill_recency_weights(roles, current_focus=current_focus)

    if not recency_weights:
        for m in _SKILL_PATTERNS.finditer(combined_resume_text):
            skill = m.group(0).lower()
            if skill not in recency_weights:
                recency_weights[skill] = 0.5

    if structured_resume:
        for skill, weight in _structured_skill_weights(structured_resume).items():
            recency_weights[skill] = max(recency_weights.get(skill, 0.0), weight)

    weighted_skills = [
        WeightedSkill(name=skill, weight=weight)
        for skill, weight in sorted(recency_weights.items(), key=lambda x: -x[1])
    ]

    seniority = _infer_seniority(combined_resume_text)
    active_lanes = detect_active_lanes(combined_resume_text, [], current_focus=current_focus)
    target_roles = _infer_target_roles(combined_resume_text, active_lanes)
    if structured_resume:
        structured_roles = _structured_target_roles(structured_resume)
        target_roles = _dedupe_keep_order([*structured_roles, *target_roles])[:8]
    active_lanes = detect_active_lanes(combined_resume_text, target_roles, current_focus=current_focus)
    domains = _infer_domains(combined_resume_text, weighted_skills)

    top_skills = [ws.name for ws in weighted_skills if ws.weight >= 0.7]
    if not top_skills:
        top_skills = [ws.name for ws in weighted_skills[:8] if ws.weight >= 0.4]
    must_have = _select_must_have_terms(
        [ws for ws in weighted_skills if ws.name in top_skills] or weighted_skills,
        active_lanes,
    )

    avoid = ["support engineer", "qa engineer", "entry level", "intern"]
    for lane_name in active_lanes:
        lane = LANE_REGISTRY.get(lane_name)
        if lane:
            avoid.extend(lane.negative_terms)
    if "network" in active_lanes:
        avoid += ["full stack developer", "frontend developer"]
    if "innovation" not in active_lanes and "r_and_d" not in active_lanes:
        avoid += ["research intern", "academic researcher"]
    if "sap_erp" in active_lanes:
        avoid += ["machine learning engineer", "ai engineer", "computer vision", "research scientist", "data engineer", "rpa", "devops"]
    if "iot" in active_lanes or "conversational_ai" in active_lanes:
        avoid += ["microservices engineer", "systems integration specialist", "ai systems architect", "computer vision engineer"]

    # Apply per-user config_overrides (replaces hardcoded candidate customizations)
    if profile_cfg.get("target_roles"):
        target_roles = profile_cfg["target_roles"]
    preferred_locations = (
        profile_cfg.get("preferred_locations")
        or (_structured_locations(structured_resume) if structured_resume else None)
        or _extract_locations(combined_resume_text)
    )
    if profile_cfg.get("must_have_terms"):
        extras = [t for t in profile_cfg["must_have_terms"] if t not in must_have]
        must_have = (must_have + extras)[:8]
    if profile_cfg.get("avoid_terms"):
        avoid.extend(profile_cfg["avoid_terms"])
    preferred_company_tiers = _structured_company_preferences(profile_cfg)
    company_preference_strength = float(profile_cfg.get("company_preference_strength") or 1.0)

    # Build company tier lookup from base config (same as V2's CompanyScorer)
    company_tier_map = _build_company_tier_map()

    return CandidateProfile(
        target_roles=target_roles,
        weighted_skills=weighted_skills,
        domains=domains,
        industries=["Technology"],
        seniority_band=seniority,
        preferred_locations=preferred_locations,
        must_have_terms=must_have,
        avoid_terms=list(dict.fromkeys(avoid))[:12],
        current_focus=current_focus,
        active_lanes=active_lanes,
        years_of_experience=_structured_years_of_experience(structured_resume) if structured_resume else None,
        company_tier_map=company_tier_map,
        preferred_company_tiers=preferred_company_tiers,
        company_preference_strength=company_preference_strength,
    )


def _build_company_tier_map() -> dict[str, str]:
    """Load company tier lookup from base config using CompanyScorer's normalization."""
    try:
        from batch.context import build_context
        from domain.company import CompanyScorer
        cfg = build_context(user_id="__base__", resume_text="").config
        scorer = CompanyScorer(cfg)
        return dict(scorer._tier_lookup)
    except Exception:
        return {}
