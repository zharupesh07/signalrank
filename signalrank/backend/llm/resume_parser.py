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


def _normalize_link_handle(value: object, *, kind: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.removeprefix("https://").removeprefix("http://").strip().strip("/")
    lower = cleaned.lower()
    if kind == "linkedin":
        for prefix in ("www.linkedin.com/", "linkedin.com/"):
            if lower.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                lower = cleaned.lower()
        if lower.startswith("in/"):
            cleaned = cleaned[3:]
    elif kind == "github":
        for prefix in ("www.github.com/", "github.com/"):
            if lower.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
    return cleaned.strip("/")


def _normalize_website(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.removeprefix("https://").removeprefix("http://").strip().strip("/")
    return cleaned.removeprefix("www.")

_PROMPT_TEMPLATE = """Extract structured job search data from this resume. Return a single JSON object only.

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
{resume_text}"""

EXTRACTION_PROMPT = _PROMPT_TEMPLATE.replace(
    "{role_options}", ", ".join(CANONICAL_ROLE_OPTIONS)
).replace(
    "{location_options}", ", ".join(LOCATION_OPTIONS)
)


def _build_extraction_prompt(resume_text: str) -> str:
    return EXTRACTION_PROMPT.format(resume_text=resume_text[:10000])


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


_STRUCTURE_PROMPT = """Extract the complete structured content from this resume. Return a single JSON object.

Rules:
- Extract EVERY piece of information — do not summarize or omit details.
- Each experience MUST include ALL bullet points from the original resume, word-for-word.
- Preserve original formatting of dates exactly as written.
- If a field is not present in the resume, use an empty string or empty list.
- For skills, group by category if categories are apparent; otherwise use "General".
- For certifications, include only the certification name (not descriptions).
- linkedin and github should be just the handle/username, not the full URL.

Keys:
- name: full name (string)
- email: email address (string)
- phone: phone number with country code (string)
- location: city, state/country (string)
- linkedin: LinkedIn handle only, e.g. "john-doe" (string)
- github: GitHub username only (string)
- website: personal website domain (string)
- position: current job title or professional headline (string)
- summary: professional summary paragraph (string)
- experiences: list of objects with keys: title, company, dates, location, bullets (list of strings)
- skills: list of objects with keys: category (string), items (list of strings)
- projects: list of objects with keys: name, url, description
- education: list of objects with keys: degree, institution, year
- certifications: list of certification name strings

Return JSON only. No explanations.

RESUME:
{resume_text}"""


async def parse_resume_structure(
    resume_text: str,
    llm_client: OpenRouterClient,
) -> dict:
    if not (resume_text or "").strip():
        return {}
    prompt = _STRUCTURE_PROMPT.format(resume_text=resume_text[:12000])
    try:
        data = await llm_client.llm_json(prompt, max_tokens=3000)
        if "_error" in data:
            logger.warning("LLM structure parse failed: %s", data.get("_details"))
            return {}
        return _validate_structure(data)
    except Exception:
        logger.exception("Resume structure parse failed")
        return {}


def _validate_structure(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}

    def to_str(val) -> str:
        return str(val).strip() if val else ""

    def to_list(val) -> list:
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, (dict, str)):
            return [val]
        return []

    experiences = []
    for exp in to_list(data.get("experiences")):
        if isinstance(exp, dict):
            cleaned = {
                "title": to_str(exp.get("title")),
                "company": to_str(exp.get("company")),
                "dates": to_str(exp.get("dates")),
                "location": to_str(exp.get("location")),
                "bullets": [to_str(b) for b in to_list(exp.get("bullets")) if to_str(b)],
            }
            if any(cleaned.get(field) for field in ("title", "company", "dates", "location", "bullets")):
                experiences.append(cleaned)

    skills = []
    for skill in to_list(data.get("skills")):
        if isinstance(skill, dict):
            items = [to_str(i) for i in to_list(skill.get("items")) if to_str(i)]
            if items:
                skills.append({
                    "category": to_str(skill.get("category")) or "General",
                    "items": items,
                })

    projects = []
    for proj in to_list(data.get("projects")):
        if isinstance(proj, dict):
            cleaned = {
                "name": to_str(proj.get("name")),
                "url": to_str(proj.get("url")),
                "description": to_str(proj.get("description")),
            }
            if any(cleaned.get(field) for field in ("name", "url", "description")):
                projects.append(cleaned)

    education = []
    for edu in to_list(data.get("education")):
        if isinstance(edu, dict):
            cleaned = {
                "degree": to_str(edu.get("degree")),
                "institution": to_str(edu.get("institution")),
                "year": to_str(edu.get("year")),
            }
            if any(cleaned.get(field) for field in ("degree", "institution", "year")):
                education.append(cleaned)

    certifications = [to_str(c) for c in to_list(data.get("certifications")) if to_str(c)]

    return {
        "name": to_str(data.get("name")),
        "email": to_str(data.get("email")),
        "phone": to_str(data.get("phone")),
        "location": to_str(data.get("location")),
        "linkedin": _normalize_link_handle(data.get("linkedin"), kind="linkedin"),
        "github": _normalize_link_handle(data.get("github"), kind="github"),
        "website": _normalize_website(data.get("website")),
        "position": to_str(data.get("position")),
        "summary": to_str(data.get("summary")),
        "experiences": experiences,
        "skills": skills,
        "projects": projects,
        "education": education,
        "certifications": certifications,
    }


async def parse_resume(
    resume_text: str,
    llm_client: OpenRouterClient,
) -> ResumeParseResult:
    prompt = _build_extraction_prompt(resume_text)
    try:
        data = await llm_client.llm_json(prompt, max_tokens=900)
        data = _massage_parsed_data(data, resume_text)
        return _validate_extraction(data)
    except Exception:
        logger.exception("Resume parse failed — returning empty result")
        return ResumeParseResult()
