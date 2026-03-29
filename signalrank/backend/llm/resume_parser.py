import logging
import re
from dataclasses import dataclass, field

from domain.role_taxonomy import CANONICAL_ROLE_OPTIONS, ENTERPRISE_ROLE_KEYWORDS, LOCATION_OPTIONS
from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

_ROLE_LOOKUP = {role.lower(): role for role in CANONICAL_ROLE_OPTIONS}


def detect_enterprise_role_from_text(text: str) -> str | None:
    normalized_text = (text or "").lower()
    if any(keyword in normalized_text for keyword in ENTERPRISE_ROLE_KEYWORDS):
        return "SAP SD Consultant"
    return None


def _normalize_role_option(role: str) -> str | None:
    candidate = re.sub(r"\s+", " ", (role or "").strip())
    if not candidate:
        return None
    lower_candidate = candidate.lower()
    if lower_candidate in _ROLE_LOOKUP:
        return _ROLE_LOOKUP[lower_candidate]
    for option in CANONICAL_ROLE_OPTIONS:
        option_lower = option.lower()
        if option_lower in lower_candidate or lower_candidate in option_lower:
            return option
    return candidate


def _sanitize_roles(raw_roles) -> list[str]:
    if raw_roles is None:
        return []
    roles = []
    seen = set()
    iterable = raw_roles if isinstance(raw_roles, list) else [raw_roles]
    for entry in iterable:
        normalized = _normalize_role_option(str(entry))
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        roles.append(normalized)
        if len(roles) >= 5:
            break
    return roles


def _ensure_enterprise_priority(roles: list[str], resume_text: str) -> list[str]:
    enterprise = detect_enterprise_role_from_text(resume_text)
    if not enterprise:
        return roles
    lower_roles = [role.lower() for role in roles]
    if enterprise.lower() in lower_roles:
        idx = lower_roles.index(enterprise.lower())
        if idx != 0:
            roles.insert(0, roles.pop(idx))
    else:
        roles.insert(0, enterprise)
    return roles


def _massage_parsed_data(data: dict, resume_text: str) -> dict:
    if not isinstance(data, dict):
        return data
    cleaned = _sanitize_roles(data.get("suggested_roles"))
    cleaned = _ensure_enterprise_priority(cleaned, resume_text)
    if cleaned:
        data["suggested_roles"] = cleaned
    else:
        data.pop("suggested_roles", None)
    return data

EXTRACTION_PROMPT = """Extract structured job search data from this resume. Return a single JSON object only.

Available role options (pick best matches): {role_options}
Available location options (pick based on work history): {location_options}

Rules:
- Focus on the candidate's true domain and seniority; do not default to AI/ML roles unless the resume clearly shows that focus.
- If the resume flags SAP/Sales & Distribution/ERP delivery, prioritize "SAP SD Consultant" as the top suggested role.
- Choose 1-3 roles that feel consistent with the bulk of the experience. Avoid adding multiple AI or generic roles unless the resume justifies them.
- Choose 1-3 locations that align with the candidate's recent work history.

Keys:
- skills: list of technical skills
- years_of_experience: integer or null
- recent_titles: list of 2-3 most recent job titles
- industries: list of industries worked in
- education: list of degrees/certifications
- suggested_roles: 1-3 items from the available role options that best match this profile
- suggested_locations: 1-3 items from the available location options based on where they have worked
- salary_lpa: estimated annual salary expectation as integer in LPA based on experience level and Indian market, or null
- suggested_exclusions: role keywords this person likely wants to avoid (e.g. "QA Engineer", "Support", "Consulting")

Return JSON only. No explanations.

RESUME:
{{resume_text}}"""

EXTRACTION_PROMPT = EXTRACTION_PROMPT.replace(
    "{role_options}", ", ".join(CANONICAL_ROLE_OPTIONS)
).replace(
    "{location_options}", ", ".join(LOCATION_OPTIONS)
)


@dataclass
class ResumeParseResult:
    skills: list[str] = field(default_factory=list)
    years_of_experience: int | None = None
    recent_titles: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    suggested_roles: list[str] = field(default_factory=list)
    suggested_locations: list[str] = field(default_factory=list)
    salary_lpa: int | None = None
    suggested_exclusions: list[str] = field(default_factory=list)


def _validate_extraction(data: dict) -> ResumeParseResult:
    if "_error" in data:
        return ResumeParseResult()

    def to_list(val) -> list[str]:
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str):
            return [val.strip()] if val.strip() else []
        return []

    def to_int(val) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    return ResumeParseResult(
        skills=to_list(data.get("skills")),
        years_of_experience=to_int(data.get("years_of_experience")),
        recent_titles=to_list(data.get("recent_titles")),
        industries=to_list(data.get("industries")),
        education=to_list(data.get("education")),
        suggested_roles=to_list(data.get("suggested_roles")),
        suggested_locations=to_list(data.get("suggested_locations")),
        salary_lpa=to_int(data.get("salary_lpa")),
        suggested_exclusions=to_list(data.get("suggested_exclusions")),
    )


async def parse_resume(
    resume_text: str,
    llm_client: OpenRouterClient,
) -> ResumeParseResult:
    prompt = EXTRACTION_PROMPT.format(resume_text=resume_text[:10000])
    try:
        data = await llm_client.llm_json(prompt, max_tokens=900)
        data = _massage_parsed_data(data, resume_text)
        return _validate_extraction(data)
    except Exception:
        logger.exception("Resume parse failed — returning empty result")
        return ResumeParseResult()
