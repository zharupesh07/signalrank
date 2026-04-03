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
- For suggested_search_queries: generate 3-5 specific job search strings that capture this candidate's unique skill+role combination. Each query should be a realistic job title someone would post (e.g. "SAP SD GTS Consultant", "SAP S/4HANA Order-to-Cash Consultant", "Senior Backend Engineer Python Kafka"). Vary the terms — do not just repeat the same role with minor changes. Avoid generic terms like "Software Engineer" alone.
- For suggested_exclusions: list role keywords this person likely wants to avoid based on their seniority and domain. For senior candidates avoid "Junior", "Support", "Helpdesk". For specialists avoid generic titles that dilute their expertise.
- For salary: use LPA (lakhs per annum) for India-based candidates, USD/year for international. Return as integer in LPA for India, or null if unclear.

Keys:
- skills: list of technical skills (include all domain-specific tools, platforms, and frameworks; not soft skills)
- years_of_experience: integer or null
- recent_titles: list of 2-3 most recent job titles
- industries: list of industries worked in
- education: list of degrees/certifications
- suggested_roles: 1-3 items from the available role options that best match this profile
- suggested_locations: 1-3 items from the available location options based on where they have worked
- salary_lpa: estimated annual salary expectation as integer (LPA for India, USD thousands for international), or null
- suggested_exclusions: 3-6 role keywords this person likely wants to avoid
- suggested_search_queries: 3-5 specific job search strings combining role + key differentiating skills

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
    suggested_search_queries: list[str] = field(default_factory=list)


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
        suggested_search_queries=to_list(data.get("suggested_search_queries")),
    )


_VISION_STRUCTURE_PROMPT = """You are looking at a resume image. Extract ALL structured content and return a single JSON object.

CRITICAL RULES — follow exactly:
1. Copy names, emails, phone numbers, and company names CHARACTER-FOR-CHARACTER from the image. Do NOT autocorrect spelling or substitute what you think it should be.
2. If you cannot read a company name clearly, write exactly what is visible — do NOT substitute a well-known company name from your training data.
3. Count every work experience section before writing the JSON — all of them must appear in `experiences`.
4. Education entries (B.Tech, M.S., Master of …, Bachelor of …) go ONLY in `education`. NEVER put them in `experiences`.
5. `experiences` contains only paid work / internships. A work entry has a job title (Engineer, Analyst, Manager, etc.) and a company name.
6. Extract ALL bullet points from each experience, word-for-word. Do not summarize or drop any.
7. Certifications = course/certification names only. Do NOT add project names or tech stack lines here.
8. Contact icons are stripped in the image — infer link type by pattern:
   - ends in ".github.io" → website
   - contains "/" or looks like "first-last" → linkedin handle
   - plain username without hyphens → github username
9. Lines labelled "TECH:" before bullets in a work entry → `tech` field, not a bullet.
10. NEVER invent or guess any information not visible in the image. If a field is unclear, use an empty string.

Keys:
- name: full name exactly as printed (string)
- email: email address exactly as printed (string)
- phone: phone number with country code (string)
- location: city/country where candidate is currently based (string)
- linkedin: handle only, e.g. "john-doe" (string)
- github: username only (string)
- website: domain only, e.g. "john.dev" (string)
- position: current job title or headline (string)
- summary: professional summary paragraph (string)
- experiences: list of {title, company, dates, location, tech, bullets}
- skills: list of {category, items}
- projects: list of {name, url, description}
- education: list of {degree, institution, year}
- certifications: list of strings

Return JSON only. No explanations."""


_SKILL_CATEGORIES = [
    "Programming Languages",
    "Frameworks & Libraries",
    "Cloud & Infrastructure",
    "Data & ML",
    "Databases",
    "Tools & DevOps",
    "Soft Skills",
    "Domain Knowledge",
    "Hardware",
    "Other",
]


def _resume_parse_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "skills": {"type": "array", "items": {"type": "string"}},
            "years_of_experience": {"type": ["integer", "null"]},
            "recent_titles": {"type": "array", "items": {"type": "string"}},
            "industries": {"type": "array", "items": {"type": "string"}},
            "education": {"type": "array", "items": {"type": "string"}},
            "suggested_roles": {"type": "array", "items": {"type": "string"}},
            "suggested_locations": {"type": "array", "items": {"type": "string"}},
            "salary_lpa": {"type": ["integer", "null"]},
            "suggested_exclusions": {"type": "array", "items": {"type": "string"}},
            "suggested_search_queries": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "skills",
            "years_of_experience",
            "recent_titles",
            "industries",
            "education",
            "suggested_roles",
            "suggested_locations",
            "salary_lpa",
            "suggested_exclusions",
            "suggested_search_queries",
        ],
        "additionalProperties": False,
    }


def _resume_structure_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "location": {"type": "string"},
            "linkedin": {"type": "string"},
            "github": {"type": "string"},
            "website": {"type": "string"},
            "position": {"type": "string"},
            "summary": {"type": "string"},
            "experiences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "dates": {"type": "string"},
                        "location": {"type": "string"},
                        "tech": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "company", "dates", "location", "tech", "bullets"],
                    "additionalProperties": False,
                },
            },
            "skills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": _SKILL_CATEGORIES},
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category", "items"],
                    "additionalProperties": False,
                },
            },
            "projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["name", "url", "description"],
                    "additionalProperties": False,
                },
            },
            "education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "degree": {"type": "string"},
                        "institution": {"type": "string"},
                        "year": {"type": "string"},
                    },
                    "required": ["degree", "institution", "year"],
                    "additionalProperties": False,
                },
            },
            "certifications": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "name",
            "email",
            "phone",
            "location",
            "linkedin",
            "github",
            "website",
            "position",
            "summary",
            "experiences",
            "skills",
            "projects",
            "education",
            "certifications",
        ],
        "additionalProperties": False,
    }

_STRUCTURE_PROMPT = """Extract the complete structured content from this resume. Return a single JSON object.

CRITICAL RULES — follow exactly:
1. Copy names, emails, phone numbers, company names, and certification titles CHARACTER-FOR-CHARACTER from the text. Do NOT autocorrect, rephrase, or substitute from your training knowledge.
2. If a field is not present in the resume, use an empty string or empty list — do NOT invent or guess.
3. Each experience MUST include ALL bullet points from the original resume, word-for-word. Do not summarize or drop any.
4. Education entries (B.Tech, M.S., Master of …, Bachelor of …, Diploma, Ph.D.) go ONLY in `education`. NEVER put them in `experiences`.
5. `experiences` contains only paid work / internships with a job title (Engineer, Analyst, Manager, etc.) and a company name.
6. Certifications = course/certification names ONLY — exactly as written. Do NOT add project names, tech stack lines, or anything not in a certifications/courses section.
7. For skills, assign each skill to one of these categories exactly: {skill_categories}. Do NOT create any other category name.
8. Preserve original formatting of dates exactly as written.
9. linkedin and github should be just the handle/username, not the full URL.
   - ends in ".github.io" → website field
   - contains "linkedin.com" or looks like "first-last" → linkedin handle
   - contains "github.com" or looks like a plain username → github handle
10. Lines starting with "TECH:" before bullets in a work entry → `tech` field, not a bullet.
11. "Open Source & Projects" section → projects list (not certifications).

Keys:
- name: full name (string)
- email: email address (string)
- phone: phone number with country code (string)
- location: city, state/country where candidate is based (string)
- linkedin: LinkedIn handle only, e.g. "john-doe" (string)
- github: GitHub username only (string)
- website: personal website domain (string)
- position: current job title or professional headline (string)
- summary: professional summary paragraph (string)
- experiences: list of objects with keys: title, company, dates, location, tech, bullets (list of strings)
- skills: list of objects with keys: category (string), items (list of strings)
- projects: list of objects with keys: name, url, description
- education: list of objects with keys: degree, institution, year
- certifications: list of certification/course name strings only

Return JSON only. No explanations.

RESUME:
{resume_text}"""


async def parse_resume_structure(
    resume_text: str,
    llm_client: OpenRouterClient,
) -> dict:
    if not (resume_text or "").strip():
        return {}
    prompt = _STRUCTURE_PROMPT.format(
        skill_categories=", ".join(f'"{c}"' for c in _SKILL_CATEGORIES),
        resume_text=resume_text[:12000],
    )
    try:
        data = await llm_client.llm_json(
            prompt,
            max_tokens=3000,
            json_schema=_resume_structure_schema(),
            schema_name="resume_structure",
        )
        if "_error" in data:
            logger.warning("LLM structure parse failed: %s", data.get("_details"))
            return {}
        result = _validate_structure(data)
        if resume_text.strip():
            from domain.resume_verifier import verify_against_reference

            result = verify_against_reference(result, resume_text)
        return result
    except Exception:
        logger.exception("Resume structure parse failed")
        return {}


async def parse_resume_from_images(
    page_images: list[bytes],
    llm_client,
    *,
    vision_models: list[str] | None = None,
    max_tokens: int = 4096,
    reference_text: str = "",
    request_timeout: float | None = None,
    max_retries: int | None = None,
) -> dict:
    """Parse a resume from PNG page images using a free vision LLM.

    When ``reference_text`` (PyMuPDF-extracted text) is provided it is appended
    to the prompt so the model can use the exact text to verify names, emails,
    and company names rather than guessing from the image alone.  This prevents
    hallucinations without any post-processing.

    Returns a validated editor dict, or ``{}`` on failure.
    """
    if not page_images:
        return {}

    # Build hybrid prompt: image structure + text accuracy
    prompt = _VISION_STRUCTURE_PROMPT
    if reference_text.strip():
        prompt = (
            prompt
            + "\n\nRAW TEXT EXTRACTED FROM THIS PDF"
            + " (use this for exact spelling of names, emails, phone numbers, and company names"
            + " — do NOT substitute from your training knowledge):\n"
            + reference_text[:6000]
        )

    try:
        data = await llm_client.llm_json_vision(
            page_images,
            prompt,
            max_tokens=max_tokens,
            vision_models=vision_models or None,
            request_timeout=request_timeout,
            max_retries=max_retries,
            json_schema=_resume_structure_schema(),
            schema_name="resume_structure_vision",
        )
        if "_error" in data:
            logger.warning("Vision LLM parse failed: %s", data.get("_details"))
            return {}
        result = _validate_structure(data)
        if reference_text.strip():
            from domain.resume_verifier import verify_against_reference
            result = verify_against_reference(result, reference_text)
        logger.info(
            "Vision parse succeeded: name=%r exps=%d skills=%d",
            result.get("name"), len(result.get("experiences", [])), len(result.get("skills", [])),
        )
        return result
    except Exception:
        logger.exception("Resume vision parse failed")
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

    _DEGREE_KEYWORDS = re.compile(
        r"\b(b\.?tech|m\.?tech|b\.?e\b|m\.?e\b|b\.?sc|m\.?sc|m\.?s\b|ph\.?d|bachelor|master|"
        r"mca|bca|diploma|degree|b\.?com|m\.?com|mba|llb|b\.?arch)\b",
        re.I,
    )

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

    experiences = []
    for exp in to_list(data.get("experiences")):
        if isinstance(exp, dict):
            raw_bullets = [to_str(b) for b in to_list(exp.get("bullets")) if to_str(b)]
            tech_val = to_str(exp.get("tech"))
            title = to_str(exp.get("title"))
            company = to_str(exp.get("company"))
            # Rescue: LLM put an education entry into experiences
            if _DEGREE_KEYWORDS.search(title) and not _DEGREE_KEYWORDS.search(company):
                rescued = {
                    "degree": title,
                    "institution": company,
                    "year": to_str(exp.get("dates")),
                }
                if not any(
                    e.get("degree", "").lower() == rescued["degree"].lower()
                    for e in education
                ):
                    logger.info("Rescued education entry from experiences: %r", title)
                    education.append(rescued)
                continue
            cleaned = {
                "title": title,
                "company": company,
                "dates": to_str(exp.get("dates")),
                "location": to_str(exp.get("location")),
                "tech": tech_val,
                "bullets": raw_bullets,
            }
            if any(cleaned.get(field) for field in ("title", "company", "dates", "location", "bullets")):
                experiences.append(cleaned)

    skills = []
    for skill in to_list(data.get("skills")):
        if isinstance(skill, dict):
            items = [to_str(i) for i in to_list(skill.get("items")) if to_str(i)]
            if items:
                skills.append({
                    "category": to_str(skill.get("category")) or "Other",
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
        data = await llm_client.llm_json(
            prompt,
            max_tokens=1200,
            json_schema=_resume_parse_schema(),
            schema_name="resume_parse",
        )
        data = _massage_parsed_data(data, resume_text)
        return _validate_extraction(data)
    except Exception:
        logger.exception("Resume parse failed — returning empty result")
        return ResumeParseResult()
