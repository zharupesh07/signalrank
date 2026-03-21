import logging
from dataclasses import dataclass, field

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Extract structured data from this resume. Return JSON only with these keys:
- skills: list of technical skills (strings)
- years_of_experience: integer or null
- recent_titles: list of recent job titles (strings)
- industries: list of industries worked in (strings)
- education: list of degrees/certifications (strings)

Be concise. No explanations.

RESUME:
{resume_text}"""


@dataclass
class ResumeParseResult:
    skills: list[str] = field(default_factory=list)
    years_of_experience: int | None = None
    recent_titles: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)


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
    )


async def parse_resume(
    resume_text: str,
    llm_client: OpenRouterClient,
) -> ResumeParseResult:
    prompt = EXTRACTION_PROMPT.format(resume_text=resume_text[:10000])
    try:
        data = await llm_client.llm_json(prompt, max_tokens=700)
        return _validate_extraction(data)
    except Exception:
        logger.exception("Resume parse failed — returning empty result")
        return ResumeParseResult()
