import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "resume"

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
  skills (list of str),
  experiences (list of {title, company, location, dates, tech, bullets[]}),
  projects (list of {name, url, description}),
  education (list of {degree, institution, year})
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
        raw = await llm.llm_json(system=SYSTEM_PROMPT, user=user_msg)
        return _parse_content(raw)
    except Exception as e:
        logger.warning("Resume tailoring LLM failed: %s", e)
        return TailoredContent()


def render_typst(content: TailoredContent, template: str = "classic") -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    env.filters["typst_escape"] = lambda s: str(s).replace("@", r"\@")
    tmpl = env.get_template(f"{template}.typ.j2")
    return tmpl.render(**vars(content))


def compile_pdf(typst_source: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "resume.typ"
        out = Path(tmpdir) / "resume.pdf"
        src.write_text(typst_source, encoding="utf-8")
        result = subprocess.run(
            ["typst", "compile", str(src), str(out)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"typst compile failed: {result.stderr.decode()}")
        return out.read_bytes()
