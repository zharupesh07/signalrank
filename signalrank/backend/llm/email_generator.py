import logging
from dataclasses import dataclass

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write concise cold outreach emails from a job candidate to a recruiter or hiring manager.

Rules:
- Address the recruiter by first name on the first line: "Hi {FirstName},"
- Second paragraph: state you applied for the specific role (include the job link if provided)
- Third paragraph: lead with ONE compelling story — 1-2 concrete, quantified achievements from the resume that match the JD
- Fourth paragraph: a specific ask — "15-min call" or "quick chat this week". Also add: "If you're not the right person, I'd appreciate it if you could forward this to whoever is hiring for this role."
- Last line: "Best," (signature is appended separately)
- Body text MUST be under 120 words — brevity is respect for their time
- No generic filler ("I hope this finds you well", "I'm excited", "strong match")
- Professional but direct tone
- Use \n\n between paragraphs for clear formatting
- Do NOT include the subject line in the body
- Do NOT include a signature block — that will be appended separately

Return JSON with exactly these keys:
  subject (str) — format: "{Role title} — {one differentiator} (applied)"
  body (str) — the email body text only, with \n\n between paragraphs. Do NOT repeat the subject line here.
"""


@dataclass
class GeneratedEmail:
    subject: str
    body: str
    recruiter_name: str
    company: str


async def generate_email(
    jd: str,
    company: str,
    role: str,
    recruiter_name: str,
    tailored_bullets: list[str],
    job_url: str | None,
    llm: OpenRouterClient,
) -> GeneratedEmail:
    bullets_text = "\n".join(f"- {b}" for b in tailored_bullets[:5])
    url_line = f"\nJob URL: {job_url}" if job_url else ""

    user_msg = (
        f"COMPANY: {company}\n"
        f"ROLE: {role}\n"
        f"RECRUITER NAME: {recruiter_name}{url_line}\n\n"
        f"TOP RESUME BULLETS (tailored to this JD):\n{bullets_text}\n\n"
        f"JOB DESCRIPTION:\n{jd[:2000]}"
    )

    try:
        raw = await llm.llm_json(system=SYSTEM_PROMPT, user=user_msg, max_tokens=512)
        return GeneratedEmail(
            subject=raw.get("subject", f"{role} at {company} (applied)"),
            body=raw.get("body", ""),
            recruiter_name=recruiter_name,
            company=company,
        )
    except Exception as e:
        logger.warning("Email generation failed: %s", e)
        return GeneratedEmail(
            subject=f"{role} at {company} (applied)",
            body="",
            recruiter_name=recruiter_name,
            company=company,
        )
