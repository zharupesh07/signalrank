import logging
from dataclasses import dataclass

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write concise cold outreach emails from a job candidate to a recruiter or hiring manager.

Rules:
- Address the recruiter by first name on the first line: "Hi {FirstName},"
- Second paragraph: state you applied for the specific role; if a job URL is provided, hyperlink the role title with it like: [Role Title](url)
- Third paragraph: ONE compelling achievement — 1-2 concrete, quantified results from the resume that directly map to the JD. Be specific, no fluff.
- Fourth paragraph: soft close — do NOT ask for a call. Instead: "Happy to connect if useful — and if you're not the right person, would really appreciate a forward to whoever is hiring for this."
- Last line: "Best," (signature is appended separately)
- Body MUST be under 110 words — brevity is respect for their time
- No filler ("I hope this finds you well", "I'm excited", "strong match", "perfect fit")
- Professional but direct tone
- Use \n\n between paragraphs
- Do NOT include the subject line in the body
- Do NOT include a signature block — appended separately

Return JSON with exactly these keys:
  subject (str) — format: "{Role title} — {one sharp differentiator} (applied)"
  body (str) — email body only, \n\n between paragraphs. Do NOT repeat subject here.
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
