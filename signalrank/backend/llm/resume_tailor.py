import logging
import re
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from struct import unpack
from urllib.parse import urlparse

import yaml
from jinja2 import Environment, FileSystemLoader

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_DATE_LINE_RE = re.compile(
    r"(?i)\b(?:\d{1,2}/\d{4}|[A-Za-z]{3,9}\s+\d{4}|\d{4})\b.*(?:present|\d{4})"
)
_SECTION_TERMINATORS = {
    "education",
    "projects",
    "certifications",
    "skills",
    "technical skills",
    "summary",
    "open source & projects",
}
_TYPEST_SPECIAL_CHARS = ("\\", "#", "[", "]", "{", "}", "$", "@")


def _looks_like_location(line: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(line or "")).strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if cleaned in {"|", "·", "-", "–", "—", "/", ","}:
        return False
    location_indicators = (
        "india",
        "usa",
        "uk",
        "remote",
        "hybrid",
        "bengaluru",
        "bangalore",
        "mumbai",
        "pune",
        "delhi",
        "hyderabad",
        "chennai",
        "kolkata",
        "noida",
        "gurugram",
        "gurgaon",
        "new york",
        "san francisco",
        "london",
    )
    if any(loc in lower for loc in location_indicators):
        return len(cleaned.split()) <= 5
    if "·" in cleaned and len(cleaned.split()) <= 5:
        return True
    return False


def _resume_lines(resume_text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip(" -\t") for line in (resume_text or "").splitlines() if line.strip()]


def _looks_like_name(line: str) -> bool:
    if not line or "@" in line or any(ch.isdigit() for ch in line):
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 5:
        return False
    return all(re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", word) for word in words)


def _extract_contact_facts(resume_text: str) -> dict[str, str]:
    lines = _resume_lines(resume_text)
    top_lines = lines[:12]
    text = "\n".join(top_lines)
    facts = {
        "name": next((line for line in top_lines if _looks_like_name(line)), ""),
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "homepage": "",
        "location": "",
    }

    handle_candidates: list[str] = []
    email_match = _EMAIL_RE.search(text)
    if email_match:
        facts["email"] = email_match.group(0)

    phone_match = _PHONE_RE.search(text)
    if phone_match:
        facts["phone"] = re.sub(r"\s+", " ", phone_match.group(1)).strip()

    for line in top_lines:
        lower = line.lower()
        if "linkedin.com/" in lower:
            facts["linkedin"] = line.split("linkedin.com/", 1)[1].strip().strip("/")
        elif "github.com/" in lower:
            facts["github"] = line.split("github.com/", 1)[1].strip().strip("/")
        elif not facts["homepage"] and (
            lower.startswith("www.")
            or re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", lower)
        ):
            facts["homepage"] = line.strip().removeprefix("https://").removeprefix("http://").strip("/")
        elif (
            line
            and " " not in line
            and "@" not in line
            and ":" not in line
            and "/" not in line
            and len(line) <= 40
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        ):
            handle_candidates.append(line)
        elif (
            not facts["location"]
            and facts["email"]
            and facts["phone"]
            and "linkedin.com/" not in lower
            and "github.com/" not in lower
            and "@" not in lower
            and not _looks_like_name(line)
            and len(line) <= 80
            ):
            facts["location"] = line

    unique_handles: list[str] = []
    seen_handles: set[str] = set()
    for candidate in handle_candidates:
        key = candidate.lower()
        if key not in seen_handles:
            seen_handles.add(key)
            unique_handles.append(candidate)
    if unique_handles and (len(unique_handles) >= 2 or any("-" in candidate or "." in candidate for candidate in unique_handles)):
        if not facts["linkedin"]:
            linked_candidate = next((candidate for candidate in unique_handles if "-" in candidate or "." in candidate), "")
            if linked_candidate:
                facts["linkedin"] = linked_candidate
        if not facts["github"]:
            github_candidate = next((candidate for candidate in unique_handles if "." not in candidate and "-" not in candidate), "")
            if github_candidate:
                facts["github"] = github_candidate

    return facts


def _extract_experience_facts(resume_text: str) -> list[dict[str, str]]:
    lines = _resume_lines(resume_text)
    start_idx = next(
        (idx for idx, line in enumerate(lines) if line.lower() in {"work experience", "professional experience", "experience"}),
        None,
    )
    if start_idx is None:
        return []

    facts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    i = start_idx + 1
    while i < len(lines):
        line = lines[i]
        lower = line.lower()
        if lower in _SECTION_TERMINATORS:
            break

        title = company = dates = location = ""

        if i + 1 < len(lines) and _DATE_LINE_RE.search(lines[i + 1]):
            header = line
            for delimiter in (" – ", " — ", " - "):
                if delimiter in header:
                    left, right = header.rsplit(delimiter, 1)
                    title, company = left.strip(), right.strip()
                    dates = lines[i + 1].strip()
                    break

        if not dates and _DATE_LINE_RE.search(line):
            dates = line.strip()
            if i >= 2:
                title = lines[i - 2]
                company = lines[i - 1]

        if title and company and dates:
            if i + 1 < len(lines):
                next_line = lines[i + 1] if _DATE_LINE_RE.search(line) else lines[i + 2] if i + 2 < len(lines) else ""
                if next_line and not _DATE_LINE_RE.search(next_line) and len(next_line) <= 80 and "@" not in next_line:
                    location = next_line
            key = (title.lower(), company.lower(), dates.lower())
            if key not in seen:
                seen.add(key)
                facts.append({
                    "title": title,
                    "company": company,
                    "dates": dates,
                    "location": location,
                })
        i += 1

    return facts


def _apply_resume_facts(content: "TailoredContent", resume_text: str) -> "TailoredContent":
    contact_facts = _extract_contact_facts(resume_text)
    for field_name, value in contact_facts.items():
        if value and not getattr(content, field_name, ""):
            setattr(content, field_name, value)

    experience_facts = _extract_experience_facts(resume_text)
    if not content.experiences and experience_facts:
        content.experiences = [dict(fact, bullets=[]) for fact in experience_facts[:3]]
    elif content.experiences and experience_facts:
        for exp, fact in zip(content.experiences, experience_facts):
            for field_name in ("title", "company", "dates", "location"):
                if fact.get(field_name):
                    exp[field_name] = fact[field_name]

    return content


def _normalize_email(email: str) -> str:
    return re.sub(r"\s+", "", (email or "")).strip()


def _strip_known_prefix(value: str, *prefixes: str) -> str:
    stripped = value.strip()
    lower = stripped.lower()
    for prefix in prefixes:
        prefix_lower = prefix.lower()
        if lower.startswith(prefix_lower):
            stripped = stripped[len(prefix):]
            lower = stripped.lower()
    return stripped.strip().strip("/")


def _normalize_contact_handle(value: str, *, kind: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.removeprefix("https://").removeprefix("http://").strip().strip("/")
    if kind == "linkedin":
        cleaned = _strip_known_prefix(cleaned, "linkedin.com", "www.linkedin.com")
        cleaned = _strip_known_prefix(cleaned, "in")
    elif kind == "github":
        cleaned = _strip_known_prefix(cleaned, "github.com", "www.github.com")
    return cleaned.strip("/")


def _normalize_public_url(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith(("mailto:", "http://", "https://")):
        return cleaned
    if cleaned.startswith("www."):
        return f"https://{cleaned}"
    parsed = urlparse(f"https://{cleaned}")
    return parsed.geturl()


def _contact_link_target(kind: str, value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if kind == "email":
        return f"mailto:{_normalize_email(cleaned)}"
    if kind == "linkedin":
        handle = _normalize_contact_handle(cleaned, kind="linkedin")
        return f"https://www.linkedin.com/in/{handle}" if handle else ""
    if kind == "github":
        handle = _normalize_contact_handle(cleaned, kind="github")
        return f"https://github.com/{handle}" if handle else ""
    if kind == "homepage":
        return _normalize_public_url(cleaned)
    return cleaned


def _canonicalize_link_target(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("mailto:"):
        return cleaned
    return cleaned.rstrip("/")


def _normalize_tailored_content(content: "TailoredContent") -> "TailoredContent":
    content.email = _normalize_email(content.email)
    content.linkedin = _normalize_contact_handle(content.linkedin, kind="linkedin")
    content.github = _normalize_contact_handle(content.github, kind="github")
    content.homepage = _strip_known_prefix(
        (content.homepage or "").strip().removeprefix("https://").removeprefix("http://"),
        "www.",
    )

    deduped_skills: list[dict | str] = []
    category_map: dict[str, dict] = {}
    for entry in content.skills:
        if isinstance(entry, dict):
            category = str(entry.get("category", "")).strip()
            items = entry.get("items", []) or []
            key = category.lower()
            if key not in category_map:
                category_map[key] = {"category": category, "items": []}
                deduped_skills.append(category_map[key])
            seen_items = {str(item).strip().lower() for item in category_map[key]["items"]}
            for item in items:
                normalized_item = str(item).strip()
                if normalized_item and normalized_item.lower() not in seen_items:
                    category_map[key]["items"].append(normalized_item)
                    seen_items.add(normalized_item.lower())
        else:
            normalized_item = str(entry).strip()
            if normalized_item and normalized_item.lower() not in {str(v).strip().lower() for v in deduped_skills if not isinstance(v, dict)}:
                deduped_skills.append(normalized_item)
    content.skills = deduped_skills

    deduped_projects: list[dict] = []
    seen_projects: set[tuple[str, str]] = set()
    for project in content.projects:
        name = str(project.get("name", "")).strip()
        url = _normalize_public_url(project.get("url"))
        key = (name.lower(), url.lower())
        if not name or key in seen_projects:
            continue
        seen_projects.add(key)
        normalized_project = dict(project)
        normalized_project["name"] = name
        if url:
            normalized_project["url"] = url
        deduped_projects.append(normalized_project)
    content.projects = deduped_projects

    deduped_certs: list[dict | str] = []
    seen_certs: set[tuple[str, str]] = set()
    for cert in content.certifications:
        if isinstance(cert, dict):
            name = str(cert.get("name", "")).strip()
            url = _normalize_public_url(cert.get("url"))
            key = (name.lower(), url.lower())
            if not name or key in seen_certs:
                continue
            seen_certs.add(key)
            normalized = dict(cert)
            normalized["name"] = name
            if url:
                normalized["url"] = url
            deduped_certs.append(normalized)
        else:
            name = str(cert).strip()
            key = (name.lower(), "")
            if not name or key in seen_certs:
                continue
            seen_certs.add(key)
            deduped_certs.append(name)
    content.certifications = deduped_certs

    for exp in content.experiences:
        if exp.get("company_url"):
            exp["company_url"] = _normalize_public_url(exp.get("company_url"))
        if "bullets" in exp:
            cleaned_bullets: list[str] = []
            for bullet in exp["bullets"]:
                cleaned_bullet = _clean_bullet(bullet)
                if not cleaned_bullet or _looks_like_location(cleaned_bullet):
                    continue
                cleaned_bullets.append(cleaned_bullet)
            exp["bullets"] = cleaned_bullets

    cleaned_experiences: list[dict] = []
    for exp in content.experiences:
        cleaned = dict(exp)
        if cleaned.get("title") or cleaned.get("company") or cleaned.get("dates") or cleaned.get("location") or cleaned.get("bullets"):
            cleaned_experiences.append(cleaned)
    content.experiences = cleaned_experiences
    return content


def _clean_bullet(text: str) -> str:
    """Normalize a bullet string for safe Typst string literal insertion."""
    # Collapse all whitespace/newlines to single space (newlines break Typst strings)
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    # Add missing space between lowercase letter and uppercase (camelCase artifact)
    # but skip known acronyms pattern like "MLOps", "DevOps", "LangGraph"
    cleaned = re.sub(r"([a-z]{2,})([A-Z][a-z])", r"\1 \2", cleaned)
    # Add missing space between word and number: "for300" → "for 300"
    cleaned = re.sub(r"([a-zA-Z]{2,})(\d)", r"\1 \2", cleaned)
    # Add missing space between number and letter: "14,000deployments" → "14,000 deployments"
    cleaned = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", cleaned)
    # Curly/smart quotes → straight quotes (for Typst string safety)
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    cleaned = re.sub(r"^([a-z])", lambda match: match.group(1).upper(), cleaned)
    return cleaned


def _looks_like_stray_bullet_title(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        return False
    lowered = text.lower()
    if text.startswith(("-", "•", "*")):
        return True
    if any(sep in text for sep in (".", ";", ":", " - ", " — ", " – ")):
        return False
    if re.search(r"\b(?:built|led|implemented|developed|designed|created|improved|reduced|engineered|configured|delivered|managed|owned|collaborated|architected)\b", lowered):
        return True
    if lowered[:1].islower():
        return True
    return False


def _typst_bold(s: str) -> str:
    """Convert Markdown **text** to Typst *text* (single asterisk = bold in Typst)."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", str(s))


def _typst_escape(value: object) -> str:
    text = str(value or "")
    for char in _TYPEST_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "resume"
FONTS_DIR = Path(__file__).parent.parent / "data" / "fonts"

SYSTEM_PROMPT = """You are a resume optimization expert.
Given a candidate's resume and a job description, rewrite the resume to maximize relevance to this specific role.

Rules:
- Keep it truthful — rephrase and reorder, never fabricate
- Copy employer names, job titles, and employment dates exactly from the resume. Do not rename companies or roles.
- Mirror keywords from the JD naturally
- Quantify achievements where the original has data
- Keep to ONE page: use 4-5 tight bullet points per role, no filler
- Return JSON ONLY with exactly these keys:
  name (str), email (str), phone (str), location (str), homepage (str), linkedin (str), github (str),
  position (str, one-line title/headline),
  summary (str, 2-3 sentences max),
  skills (list of {category, items[]}),
  experiences (list of {title, company, company_url, location, dates, tech, bullets[]}),
  projects (list of {name, url, description}),
  education (list of {degree, institution, year}),
  certifications (list[str], copy from resume as-is)
"""


@dataclass
class TailoredContent:
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    homepage: str = ""
    linkedin: str = ""
    github: str = ""
    position: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    experiences: list[dict] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    par_leading: str = "0.52em"
    list_spacing: str = "0.4em"
    base_font_size: str = "8.8pt"


@dataclass
class ResumeValidationReport:
    page_count: int
    missing_links: list[str] = field(default_factory=list)
    pdf_links: list[str] = field(default_factory=list)
    vertical_fill_pct: float | None = None
    ink_fill_pct: float | None = None
    warnings: list[str] = field(default_factory=list)
    fit_actions: list[str] = field(default_factory=list)


def _parse_content(raw: dict) -> TailoredContent:
    return TailoredContent(
        name=raw.get("name", ""),
        email=raw.get("email", ""),
        phone=raw.get("phone", ""),
        location=raw.get("location", ""),
        homepage=raw.get("homepage", ""),
        linkedin=raw.get("linkedin", ""),
        github=raw.get("github", ""),
        position=raw.get("position", ""),
        summary=raw.get("summary", ""),
        skills=raw.get("skills", []),
        experiences=raw.get("experiences", []),
        projects=raw.get("projects", []),
        education=raw.get("education", []),
        certifications=raw.get("certifications", []),
    )


async def tailor_resume(
    resume_text: str,
    job_title: str,
    job_description: str,
    llm: OpenRouterClient,
) -> TailoredContent:
    user_msg = (
        f"RESUME:\n{resume_text}\n\n"
        f"JOB TITLE: {job_title}\n\n"
        f"JOB DESCRIPTION:\n{job_description[:3000]}"
    )
    try:
        raw = await llm.llm_json(system=SYSTEM_PROMPT, user=user_msg, max_tokens=2048)
        return _normalize_tailored_content(_apply_resume_facts(_parse_content(raw), resume_text))
    except Exception as e:
        logger.warning("Resume tailoring LLM failed: %s", e)
        return _normalize_tailored_content(_apply_resume_facts(TailoredContent(), resume_text))


def load_resume_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resume_yaml_to_text(data: dict) -> str:
    lines = [f"Name: {data.get('name', '')}"]
    lines.append(f"Position: {data.get('position', '')}")
    if data.get("summary"):
        lines.append(f"Summary: {data['summary']}")
    for exp in data.get("experiences", []):
        lines.append(
            f"\n{exp['title']} at {exp['company']}"
            f" ({exp.get('dates', '')})"
        )
        if exp.get("tech"):
            lines.append(f"  Tech: {exp['tech']}")
        for b in exp.get("bullets", []):
            lines.append(f"  - {b}")
    if data.get("skills"):
        lines.append("\nSkills:")
        for cat in data["skills"]:
            if isinstance(cat, dict):
                lines.append(f"  {cat['category']}: {', '.join(cat['items'])}")
            else:
                lines.append(f"  {cat}")
    for p in data.get("projects", []):
        lines.append(f"Project: {p['name']} — {p.get('description', '')}")
    for edu in data.get("education", []):
        lines.append(f"Education: {edu['degree']} at {edu['institution']}")
    return "\n".join(lines)


def check_page_count(pdf_bytes: bytes) -> int:
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except ImportError:
        content = pdf_bytes[:2048].decode("latin-1", errors="replace")
        count = content.count("/Type /Page") - content.count("/Type /Pages")
        return max(count, 1)


def _fit_to_one_page(content: TailoredContent, current_pages: int = 2) -> bool:
    """Trim content to fit one page. Returns True if any trimming was done.

    Priority (least destructive first):
    1. Truncate summary to 2 sentences if > 3
    2. Tighten paragraph leading slightly
    3. Tighten list spacing slightly
    4. Trim bullets from oldest non-intern role (reversed list = oldest first)
    5. Drop oldest role entirely as a last resort when there are many roles
    """
    if current_pages <= 1:
        return False

    # Step 1: trim summary
    sentences = [s.strip() for s in content.summary.split(".") if s.strip()]
    if len(sentences) > 3:
        content.summary = ". ".join(sentences[:2]) + "."
        return True

    # Step 2: tighten line spacing before removing content
    if content.par_leading != "0.48em":
        content.par_leading = "0.48em"
        return True

    # Step 3: tighten list spacing before removing content
    if content.list_spacing != "0.25em":
        content.list_spacing = "0.25em"
        return True

    # Step 4: trim oldest non-intern role first (reversed = oldest first)
    non_intern = [e for e in reversed(content.experiences) if e.get("bullets")]
    for exp in non_intern:
        bullets = exp.get("bullets", [])
        is_newest = content.experiences.index(exp) == 0
        floor = 3 if is_newest else 2
        if len(bullets) > floor:
            exp["bullets"] = bullets[:-1]
            return True

    # Step 5: if still too long, drop the oldest role entirely.
    if len(content.experiences) > 3:
        content.experiences.pop()
        return True

    return False


def _expand_to_fill_page(content: TailoredContent, vertical_fill_pct: float) -> bool:
    """Increase spacing/font when the page is underfilled. Inverse of _fit_to_one_page.

    Returns True if any change was made (caller should re-render).
    """
    if vertical_fill_pct >= 65:
        return False

    if content.par_leading == "0.48em":
        content.par_leading = "0.52em"
        return True
    if content.list_spacing == "0.25em":
        content.list_spacing = "0.4em"
        return True
    if vertical_fill_pct < 60 and content.par_leading == "0.52em":
        content.par_leading = "0.65em"
        return True
    if vertical_fill_pct < 60 and content.list_spacing == "0.4em":
        content.list_spacing = "0.55em"
        return True
    if vertical_fill_pct < 50 and content.base_font_size == "8.8pt":
        content.base_font_size = "9.2pt"
        return True
    if vertical_fill_pct < 45 and content.base_font_size == "9.2pt":
        content.base_font_size = "9.5pt"
        return True
    return False


def _render_metrics(content: TailoredContent) -> dict:
    return {
        "summary": (content.summary or "").strip(),
        "par_leading": content.par_leading,
        "list_spacing": content.list_spacing,
        "experience_count": len(content.experiences),
        "bullet_count": sum(len(exp.get("bullets", []) or []) for exp in content.experiences),
    }


def _describe_fit_actions(before: dict, after: TailoredContent) -> list[str]:
    actions: list[str] = []
    if before.get("summary") and (after.summary or "").strip() != before["summary"]:
        if len((after.summary or "").strip()) < len(before["summary"]):
            actions.append("Summary was shortened to fit one page")
    if before.get("par_leading") != after.par_leading:
        actions.append("Line spacing was tightened to fit one page")
    if before.get("list_spacing") != after.list_spacing:
        actions.append("Bullet spacing was tightened to fit one page")

    bullet_delta = before.get("bullet_count", 0) - sum(len(exp.get("bullets", []) or []) for exp in after.experiences)
    if bullet_delta > 0:
        noun = "bullet point" if bullet_delta == 1 else "bullet points"
        verb = "was" if bullet_delta == 1 else "were"
        actions.append(f"{bullet_delta} {noun} {verb} removed to fit one page")

    dropped_experiences = before.get("experience_count", 0) - len(after.experiences)
    if dropped_experiences > 0:
        noun = "older experience entry" if dropped_experiences == 1 else "older experience entries"
        verb = "was" if dropped_experiences == 1 else "were"
        actions.append(f"{dropped_experiences} {noun} {verb} removed to fit one page")

    return actions


def _expected_resume_links(content: TailoredContent) -> list[str]:
    links: list[str] = []
    for kind, value in (
        ("email", content.email),
        ("linkedin", content.linkedin),
        ("github", content.github),
        ("homepage", content.homepage),
    ):
        target = _contact_link_target(kind, value)
        if target:
            links.append(_canonicalize_link_target(target))
    for exp in content.experiences:
        target = _normalize_public_url(exp.get("company_url"))
        if target:
            links.append(_canonicalize_link_target(target))
    for project in content.projects:
        target = _normalize_public_url(project.get("url"))
        if target:
            links.append(_canonicalize_link_target(target))
    for cert in content.certifications:
        if isinstance(cert, dict):
            target = _normalize_public_url(cert.get("url"))
            if target:
                links.append(_canonicalize_link_target(target))
    return sorted(set(links))


def _pdf_annotation_links(pdf_bytes: bytes) -> list[str]:
    import io
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    links: set[str] = set()
    for page in reader.pages:
        for annot in page.get("/Annots", []) or []:
            obj = annot.get_object()
            action = obj.get("/A")
            if action and action.get("/URI"):
                links.add(_canonicalize_link_target(str(action.get("/URI"))))
    return sorted(links)


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _decode_png_rows(png_bytes: bytes) -> tuple[int, int, int, int, list[bytes]]:
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG header")

    width = height = bit_depth = color_type = 0
    idat = bytearray()
    cursor = 8
    while cursor < len(png_bytes):
        chunk_len = unpack(">I", png_bytes[cursor:cursor + 4])[0]
        chunk_type = png_bytes[cursor + 4:cursor + 8]
        chunk_data = png_bytes[cursor + 8:cursor + 8 + chunk_len]
        cursor += 12 + chunk_len
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = unpack(">IIBBBBB", chunk_data)
            if compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("Unsupported PNG encoding")
            if bit_depth != 8:
                raise ValueError("Unsupported PNG bit depth")
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if not channels:
        raise ValueError(f"Unsupported PNG color type: {color_type}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows: list[bytes] = []
    pos = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scanline = bytearray(raw[pos:pos + stride])
        pos += stride
        if filter_type == 1:
            for i in range(stride):
                left = scanline[i - channels] if i >= channels else 0
                scanline[i] = (scanline[i] + left) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                scanline[i] = (scanline[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = scanline[i - channels] if i >= channels else 0
                up = prev[i]
                scanline[i] = (scanline[i] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = scanline[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                scanline[i] = (scanline[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"Unsupported PNG filter: {filter_type}")
        rows.append(bytes(scanline))
        prev = scanline
    return width, height, channels, color_type, rows


def _png_fill_metrics(png_bytes: bytes) -> tuple[float, float]:
    width, height, channels, color_type, rows = _decode_png_rows(png_bytes)
    total_pixels = width * height
    ink_pixels = 0
    first_nonwhite = None
    last_nonwhite = None

    for row_idx, row in enumerate(rows):
        row_has_content = False
        for px_idx in range(0, len(row), channels):
            if color_type == 0:
                gray = row[px_idx]
                alpha = 255
            elif color_type == 2:
                r, g, b = row[px_idx:px_idx + 3]
                gray = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
                alpha = 255
            elif color_type == 4:
                gray, alpha = row[px_idx:px_idx + 2]
            else:
                r, g, b, alpha = row[px_idx:px_idx + 4]
                gray = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
            if alpha > 10 and gray < 245:
                ink_pixels += 1
                row_has_content = True
        if row_has_content:
            if first_nonwhite is None:
                first_nonwhite = row_idx
            last_nonwhite = row_idx

    vertical_fill_pct = 0.0
    if first_nonwhite is not None and last_nonwhite is not None:
        vertical_fill_pct = ((last_nonwhite - first_nonwhite + 1) / height) * 100
    ink_fill_pct = (ink_pixels / total_pixels) * 100 if total_pixels else 0.0
    return round(vertical_fill_pct, 2), round(ink_fill_pct, 2)


def _has_fragmented_bullets(content: "TailoredContent") -> bool:
    for exp in content.experiences:
        bullets = [str(bullet or "").strip() for bullet in (exp.get("bullets") or []) if str(bullet or "").strip()]
        if len(bullets) < 6:
            continue
        short_count = sum(1 for bullet in bullets if len(bullet) < 55)
        lowercase_starts = sum(1 for bullet in bullets if bullet[:1].islower())
        if short_count >= max(4, len(bullets) // 2) or lowercase_starts >= 2:
            return True
    return False


def _render_first_page_png(typst_source: str) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "resume.typ"
        out_pattern = Path(tmpdir) / "resume-{p}.png"
        src.write_text(typst_source, encoding="utf-8")
        cmd = ["typst", "compile", "--format", "png", str(src), str(out_pattern)]
        if FONTS_DIR.exists():
            cmd[2:2] = ["--font-path", str(FONTS_DIR)]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.warning("typst png compile failed: %s", result.stderr.decode())
            return None
        pages = sorted(Path(tmpdir).glob("resume-*.png"))
        if not pages:
            return None
        return pages[0].read_bytes()


def validate_resume_artifacts(
    content: TailoredContent,
    typst_source: str,
    pdf_bytes: bytes,
    *,
    fit_actions: list[str] | None = None,
) -> ResumeValidationReport:
    expected_links = _expected_resume_links(content)
    pdf_links = _pdf_annotation_links(pdf_bytes)
    missing_links = [link for link in expected_links if link not in pdf_links]

    warnings: list[str] = []
    page_count = check_page_count(pdf_bytes)
    if page_count > 1:
        warnings.append(f"Resume still renders to {page_count} pages")
    if missing_links:
        warnings.append("Some expected hyperlinks are missing from the rendered PDF")
    if _has_fragmented_bullets(content):
        warnings.append("Resume contains fragmented bullet lines that should be merged before rendering")
    if fit_actions:
        warnings.append("Resume required layout compression to fit")

    vertical_fill_pct = None
    ink_fill_pct = None
    png_bytes = _render_first_page_png(typst_source)
    if png_bytes:
        vertical_fill_pct, ink_fill_pct = _png_fill_metrics(png_bytes)
        if vertical_fill_pct < 65:
            warnings.append("Resume leaves significant vertical space unused")

    return ResumeValidationReport(
        page_count=page_count,
        missing_links=missing_links,
        pdf_links=pdf_links,
        vertical_fill_pct=vertical_fill_pct,
        ink_fill_pct=ink_fill_pct,
        warnings=warnings,
        fit_actions=fit_actions or [],
    )


def render_typst(content: TailoredContent, template: str = "classic") -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    env.filters["typst_escape"] = _typst_escape
    env.filters["typst_bold"] = _typst_bold
    tmpl = env.get_template(f"{template}.typ.j2")
    return tmpl.render(**vars(_normalize_tailored_content(content)))


def compile_pdf(typst_source: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "resume.typ"
        out = Path(tmpdir) / "resume.pdf"
        src.write_text(typst_source, encoding="utf-8")
        cmd = ["typst", "compile"]
        if FONTS_DIR.exists():
            cmd += ["--font-path", str(FONTS_DIR)]
        cmd += [str(src), str(out)]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"typst compile failed: {result.stderr.decode()}")
        return out.read_bytes()


def render_and_compile_content(
    content: TailoredContent,
    template: str = "classic",
    max_pages: int = 1,
) -> tuple[str, bytes]:
    typst_src = render_typst(content, template)
    pdf = compile_pdf(typst_src)

    for _ in range(10):
        page_count = check_page_count(pdf)
        if page_count <= max_pages:
            break
        if not _fit_to_one_page(content, current_pages=page_count):
            break
        typst_src = render_typst(content, template)
        pdf = compile_pdf(typst_src)
    else:
        logger.warning("_fit_to_one_page exhausted iterations, returning best-effort PDF")

    return typst_src, pdf


def render_compile_validate_content(
    content: TailoredContent,
    template: str = "classic",
    max_pages: int = 1,
) -> tuple[str, bytes, ResumeValidationReport]:
    before = _render_metrics(content)
    typst_src, pdf = render_and_compile_content(content, template=template, max_pages=max_pages)
    fit_actions = _describe_fit_actions(before, content)
    validation = validate_resume_artifacts(content, typst_src, pdf, fit_actions=fit_actions)

    if validation.vertical_fill_pct is not None and validation.vertical_fill_pct < 65:
        for _ in range(4):
            if not _expand_to_fill_page(content, validation.vertical_fill_pct):
                break
            typst_src, pdf = render_and_compile_content(content, template=template, max_pages=max_pages)
            validation = validate_resume_artifacts(content, typst_src, pdf, fit_actions=fit_actions)
            if validation.vertical_fill_pct is None or validation.vertical_fill_pct >= 65:
                break

    return typst_src, pdf, validation


async def tailor_and_compile(
    resume_data: dict,
    job_title: str,
    job_description: str,
    llm: OpenRouterClient,
    template: str = "classic",
    max_pages: int = 1,
) -> tuple[TailoredContent, bytes]:
    resume_text = resume_yaml_to_text(resume_data)
    content = await tailor_resume(resume_text, job_title, job_description, llm)

    # Always fill contact fields from YAML (LLM often omits them)
    for field_name in ("name", "email", "phone", "linkedin", "github", "homepage", "location"):
        if not getattr(content, field_name) and resume_data.get(field_name):
            setattr(content, field_name, resume_data[field_name])

    # If LLM failed entirely, fall back to raw YAML content
    if not content.experiences:
        content.experiences = resume_data.get("experiences", [])
    if not content.skills:
        content.skills = resume_data.get("skills", [])
    if not content.projects:
        content.projects = resume_data.get("projects", [])
    if not content.summary:
        content.summary = resume_data.get("summary", "")
    if not content.certifications:
        content.certifications = resume_data.get("certifications", [])

    typst_src, pdf = render_and_compile_content(content, template=template, max_pages=max_pages)
    return content, pdf
