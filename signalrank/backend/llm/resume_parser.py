import logging
from dataclasses import dataclass, field

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

_ROLE_OPTIONS = [
    "AI/ML Engineer",
    "Data Scientist",
    "MLOps/Platform Engineer",
    "Backend Engineer",
    "Full-Stack Engineer",
    "DevOps/SRE",
    "Security Engineer",
]

_LOCATION_OPTIONS = [
    "Remote only",
    "Bangalore",
    "Hyderabad",
    "Mumbai",
    "Delhi/NCR",
    "Pune",
    "Any India",
    "Open to relocation",
]

EXTRACTION_PROMPT = """Extract structured job search data from this resume. Return JSON only.

Available role options (pick best matches): {role_options}
Available location options (pick based on work history): {location_options}

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
    "{role_options}", ", ".join(_ROLE_OPTIONS)
).replace(
    "{location_options}", ", ".join(_LOCATION_OPTIONS)
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
        return _validate_extraction(data)
    except Exception:
        logger.exception("Resume parse failed — returning empty result")
        return ResumeParseResult()
