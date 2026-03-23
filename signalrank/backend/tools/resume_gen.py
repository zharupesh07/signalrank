"""CLI: Generate a JD-tailored resume PDF + cold email.

Usage:
    python -m tools.resume_gen \
        --jd "Senior ML Engineer at Google..." \
        --company Google \
        --recruiter "Jane Smith" \
        --role "Senior ML Engineer" \
        --output ./output/
"""
import argparse
import asyncio
import os
import re
from pathlib import Path

from llm.email_generator import generate_email
from llm.openrouter import OpenRouterClient
from llm.resume_tailor import load_resume_yaml, tailor_and_compile

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_RESUME = DATA_DIR / "resume_example.yaml"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


async def main(args: argparse.Namespace) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    llm = OpenRouterClient(api_key=api_key)
    resume_data = load_resume_yaml(args.resume)

    print(f"Tailoring resume for: {args.role} at {args.company}")
    content, pdf = await tailor_and_compile(
        resume_data=resume_data,
        job_title=args.role,
        job_description=args.jd,
        llm=llm,
    )

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{slugify(args.company)}_{slugify(args.role)}"

    pdf_path = out_dir / f"{slug}_resume.pdf"
    pdf_path.write_bytes(pdf)
    print(f"Resume PDF: {pdf_path}")

    recruiter_name = args.recruiter or "Hiring Manager"
    top_bullets = []
    for exp in content.experiences[:2]:
        top_bullets.extend(exp.get("bullets", [])[:3])

    email = await generate_email(
        jd=args.jd,
        company=args.company,
        role=args.role,
        recruiter_name=recruiter_name,
        tailored_bullets=top_bullets,
        job_url=args.job_url,
        llm=llm,
    )

    email_text = f"Subject: {email.subject}\n\n{email.body}"
    email_path = out_dir / f"{slug}_email.txt"
    email_path.write_text(email_text, encoding="utf-8")
    print(f"Email: {email_path}")
    print(f"\n{'='*60}")
    print(email_text)
    print(f"{'='*60}")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Generate tailored resume + email")
    parser.add_argument("--jd", required=True, help="Job description text")
    parser.add_argument("--company", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--recruiter", default="", help="Recruiter name")
    parser.add_argument("--job-url", default=None, help="Job posting URL")
    parser.add_argument("--resume", default=str(DEFAULT_RESUME), help="Resume YAML path")
    parser.add_argument("--output", default="./output", help="Output directory")
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Error: OPENROUTER_API_KEY not set")
        raise SystemExit(1)

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
