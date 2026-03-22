"""Import job_ranker tracker CSV into SignalRank database.

Usage:
    python -m scripts.import_tracker_csv --csv-path /path/to/job_tracker.csv --user-email user@example.com

Or extract from git:
    git show main:job_ranker/users/example/job_tracker.csv > /tmp/tracker.csv
    python -m scripts.import_tracker_csv --csv-path /tmp/tracker.csv --user-email user@example.com
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from api.database import AsyncSessionLocal
from api.models import Application, JobRaw, Recruiter


STATUS_MAP = {
    "offer received": "offer",
    "applied": "applied",
    "rejected": "rejected",
    "interview scheduled": "interview",
    "phone screen": "phone_screen",
    "not applied": "interested",
    "": "interested",
}

HYPERLINK_RE = re.compile(r'=HYPERLINK\("([^"]+)","([^"]+)"\)')


def parse_priority(raw: str) -> str | None:
    if "P1" in raw:
        return "P1"
    if "P2" in raw:
        return "P2"
    if "P3" in raw:
        return "P3"
    return None


def parse_hyperlink(cell: str) -> tuple[str | None, str | None]:
    m = HYPERLINK_RE.search(cell)
    if m:
        return m.group(2).strip(), m.group(1).strip()  # (name, url)
    return None, None


def parse_unix_ms(val: str) -> datetime | None:
    if not val:
        return None
    try:
        ts = int(float(val)) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def parse_float(val: str) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def best_url(indeed: str, board: str) -> str | None:
    return board.strip() or indeed.strip() or None


async def main(csv_path: str, user_email: str) -> None:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"Read {len(rows)} rows from {csv_path}")

    async with AsyncSessionLocal() as db:
        # Look up user
        from api.models import User

        result = await db.execute(select(User).where(User.email == user_email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"User not found: {user_email}")
            return
        user_id = user.id

        # Get existing tracked job URLs
        existing_apps = await db.execute(
            select(Application.job_id).where(
                Application.user_id == user_id, Application.job_id.isnot(None)
            )
        )
        tracked_job_ids = {r[0] for r in existing_apps.all()}

        created_apps = 0
        created_jobs = 0
        created_recruiters = 0
        skipped = 0

        for row in rows:
            job_url = best_url(
                row.get("Indeed URL", ""),
                row.get("Company Board URL", ""),
            )
            if not job_url:
                skipped += 1
                continue

            # Upsert JobRaw
            job_result = await db.execute(
                select(JobRaw).where(JobRaw.job_url == job_url)
            )
            job = job_result.scalar_one_or_none()
            if not job:
                job = JobRaw(
                    job_url=job_url,
                    title=row.get("Title", "").strip() or None,
                    company=row.get("Company", "").strip() or None,
                    location=row.get("Location", "").strip() or None,
                    site="indeed" if "indeed.com" in job_url else "company",
                    date_posted=parse_unix_ms(row.get("Date Posted", "")),
                )
                db.add(job)
                await db.flush()
                created_jobs += 1

            # Skip if already tracked
            if job.id in tracked_job_ids:
                skipped += 1
                continue

            # Parse recruiter
            recruiter_id = None
            rec_name, rec_linkedin = parse_hyperlink(row.get("Referral Contact", ""))
            if rec_name or rec_linkedin:
                company = row.get("Company", "").strip()
                if rec_linkedin and company:
                    rec_result = await db.execute(
                        select(Recruiter).where(
                            Recruiter.company == company,
                            Recruiter.linkedin_url == rec_linkedin,
                        )
                    )
                    recruiter = rec_result.scalar_one_or_none()
                else:
                    recruiter = None

                if not recruiter:
                    recruiter = Recruiter(
                        company=company or None,
                        name=rec_name,
                        linkedin_url=rec_linkedin,
                    )
                    db.add(recruiter)
                    await db.flush()
                    created_recruiters += 1
                recruiter_id = recruiter.id

            # Map status
            raw_status = row.get("Status", "").strip().lower()
            status = STATUS_MAP.get(raw_status, "interested")

            # Parse scores
            system_score = parse_float(row.get("System Score", ""))
            if system_score and system_score > 1:
                system_score = system_score / 100  # normalize 86.3 -> 0.863
            resume_match = parse_float(row.get("Resume Match %", ""))
            if resume_match and resume_match > 1:
                resume_match = resume_match / 100

            app = Application(
                user_id=user_id,
                job_id=job.id,
                company=row.get("Company", "").strip() or None,
                title=row.get("Title", "").strip() or None,
                status=status,
                priority=parse_priority(row.get("Priority", "")),
                location_group=row.get("Group", "").strip() or None,
                system_score=system_score,
                resume_match_pct=resume_match,
                offer_lpa=parse_float(row.get("Offer LPA", "")),
                notes=row.get("Notes", "").strip() or None,
                recruiter_id=recruiter_id,
            )
            db.add(app)
            tracked_job_ids.add(job.id)
            created_apps += 1

        await db.commit()
        print(f"Created {created_apps} applications, {created_jobs} jobs, {created_recruiters} recruiters. Skipped {skipped} duplicates/no-url.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import job_ranker tracker CSV into SignalRank")
    parser.add_argument("--csv-path", required=True, help="Path to job_tracker.csv")
    parser.add_argument("--user-email", required=True, help="Email of the user to import for")
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, args.user_email))
