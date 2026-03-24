import logging
import re
from dataclasses import dataclass

from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write concise cold outreach emails from a job candidate to a recruiter or hiring manager.

Rules:
- DO NOT write greeting, signature, or subject — those are added automatically
- Write only the 2-3 paragraph body:
  - Paragraph 1: state you applied for the specific role; if a job URL is provided, hyperlink the role title with it like: [Role Title](url)
  - Paragraph 2: ONE compelling achievement — 1-2 concrete, quantified results from the resume that directly map to the JD. Specific, no fluff.
  - Paragraph 3: soft close — do NOT ask for a call. Write exactly: "Happy to connect if useful — and if you're not the right person, would really appreciate a forward to whoever is hiring for this."
- Body MUST be under 90 words — brevity is respect for their time
- No filler ("I hope this finds you well", "I'm excited", "strong match", "perfect fit")
- Professional but direct tone
- Blank line between paragraphs

Respond in this exact format (no JSON, no markdown):
DIFFERENTIATOR: <3-6 words that make this candidate stand out, e.g. "built 400+ agents at scale">
BODY:
<email body paragraphs>
"""


def _parse_response(text: str) -> tuple[str, str]:
    """Parse DIFFERENTIATOR and BODY from plain-text LLM response."""
    diff_match = re.search(r"DIFFERENTIATOR:\s*(.+)", text, re.IGNORECASE)
    body_match = re.search(r"BODY:\s*\n([\s\S]+)", text, re.IGNORECASE)
    differentiator = diff_match.group(1).strip().strip('"') if diff_match else ""
    body = body_match.group(1).strip() if body_match else text.strip()
    return differentiator, body


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

    first_name = recruiter_name.split()[0] if recruiter_name and recruiter_name != "Hiring Manager" else "there"
    greeting = f"Hi {first_name},"
    fallback_subject = f"{role} — application follow-up (applied)"

    try:
        raw_text = await llm.llm_text(SYSTEM_PROMPT, user_msg, max_tokens=400, temperature=0.2)
        differentiator, body_text = _parse_response(raw_text)
        subject = f"{role} — {differentiator} (applied)" if differentiator else fallback_subject
        full_body = f"{greeting}\n\n{body_text}" if body_text else ""
        logger.info("Email generated for %s @ %s (%d words)", role, company, len(full_body.split()))
        return GeneratedEmail(
            subject=subject,
            body=full_body,
            recruiter_name=recruiter_name,
            company=company,
        )
    except Exception as e:
        logger.warning("Email generation failed: %s", e)
        return GeneratedEmail(
            subject=fallback_subject,
            body="",
            recruiter_name=recruiter_name,
            company=company,
        )
