import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


def _typst_bold(s: str) -> str:
    """Convert Markdown **text** to Typst *text* (single asterisk = bold in Typst)."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", str(s))


TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "resume"
FONTS_DIR = Path(__file__).parent.parent / "data" / "fonts"

SYSTEM_PROMPT = """You are a resume optimization expert.
Given a candidate's resume and a job description, rewrite the resume to maximize relevance to this specific role.

Rules:
- Keep it truthful — rephrase and reorder, never fabricate
- Mirror keywords from the JD naturally
- Quantify achievements where the original has data
- Keep to ONE page: use 4-5 tight bullet points per role, no filler
- Return JSON ONLY with exactly these keys:
  name (str), email (str), phone (str), location (str), homepage (str), linkedin (str), github (str),
  position (str, one-line title/headline),
  summary (str, 2-3 sentences max),
  skills (list of {category, items[]}),
  experiences (list of {title, company, location, dates, tech, bullets[]}),
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
        return _parse_content(raw)
    except Exception as e:
        logger.warning("Resume tailoring LLM failed: %s", e)
        return TailoredContent()


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
    2. Trim bullets from oldest non-intern role (reversed list = oldest first)
    3. Trim bullets from newest role only as last resort (floor: 3 bullets)
    """
    if current_pages <= 1:
        return False

    # Step 1: trim summary
    sentences = [s.strip() for s in content.summary.split(".") if s.strip()]
    if len(sentences) > 3:
        content.summary = ". ".join(sentences[:2]) + "."
        return True

    # Step 2: trim oldest non-intern role first (reversed = oldest first)
    non_intern = [e for e in reversed(content.experiences) if e.get("bullets")]
    for exp in non_intern:
        bullets = exp.get("bullets", [])
        is_newest = content.experiences.index(exp) == 0
        floor = 3 if is_newest else 2
        if len(bullets) > floor:
            exp["bullets"] = bullets[:-1]
            return True

    return False


def render_typst(content: TailoredContent, template: str = "classic") -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    env.filters["typst_escape"] = lambda s: str(s).replace("@", r"\@")
    env.filters["typst_bold"] = _typst_bold
    tmpl = env.get_template(f"{template}.typ.j2")
    return tmpl.render(**vars(content))


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

    typst_src = render_typst(content, template)
    pdf = compile_pdf(typst_src)

    for _ in range(5):
        if check_page_count(pdf) <= max_pages:
            break
        if not _fit_to_one_page(content, current_pages=check_page_count(pdf)):
            break
        typst_src = render_typst(content, template)
        pdf = compile_pdf(typst_src)
    else:
        logger.warning("_fit_to_one_page exhausted 5 iterations, returning best-effort PDF")

    return content, pdf
