from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Application, JobRaw, JobResult, Run, User
from batch.job_availability import (
    JobAvailability,
    archive_expired_jobs_for_user,
    classify_job_page,
)


def test_classify_job_page_detects_expired_copy():
    availability = classify_job_page(
        url="https://in.indeed.com/viewjob?jk=2118e4e8150afcfb",
        status_code=200,
        text="<html><body>This job has expired on Indeed.</body></html>",
    )

    assert availability.status == "expired"
    assert "expired" in availability.reason.lower()


def test_classify_job_page_detects_gone_status():
    availability = classify_job_page(
        url="https://example.com/jobs/closed",
        status_code=410,
        text="",
    )

    assert availability.status == "expired"
    assert "HTTP 410" in availability.reason


def test_classify_job_page_treats_indeed_security_check_as_unknown():
    availability = classify_job_page(
        url="https://in.indeed.com/viewjob?jk=2118e4e8150afcfb",
        status_code=403,
        text="<title>Security Check - Indeed.com</title>",
    )

    assert availability.status == "unknown"
    assert "blocked" in availability.reason


@pytest.mark.asyncio
async def test_archive_expired_jobs_for_user_archives_expired_only(
    db: AsyncSession,
):
    user = User(email="availability@test.com", password_hash="x")
    run = Run(user=user, status="success", finished_at=datetime.now(timezone.utc))
    expired_job = JobRaw(
        job_url="https://example.com/jobs/expired",
        title="Expired Engineer",
        company="Example",
        description="Old role",
        location="Remote",
        site="indeed",
    )
    available_job = JobRaw(
        job_url="https://example.com/jobs/open",
        title="Open Engineer",
        company="Example",
        description="Current role",
        location="Remote",
        site="indeed",
    )
    db.add_all([user, run, expired_job, available_job])
    await db.flush()
    expired_result = JobResult(
        run_id=run.id,
        user_id=user.id,
        job_id=expired_job.id,
        final_score=90.0,
    )
    available_result = JobResult(
        run_id=run.id,
        user_id=user.id,
        job_id=available_job.id,
        final_score=80.0,
    )
    db.add_all([expired_result, available_result])
    db.add(
        Application(
            user_id=user.id,
            job_id=expired_job.id,
            company=expired_job.company,
            title=expired_job.title,
            status="interested",
        )
    )
    await db.commit()

    async def checker(url: str) -> JobAvailability:
        status = "expired" if url.endswith("/expired") else "available"
        reason = (
            "Job posting is expired or no longer available"
            if status == "expired"
            else None
        )
        return JobAvailability(url=url, status=status, reason=reason, status_code=200)

    payload = await archive_expired_jobs_for_user(
        db,
        user_id=user.id,
        urls=[
            "https://example.com/jobs/expired",
            "https://example.com/jobs/open",
        ],
        checker=checker,
    )

    assert payload["checked"] == 2
    assert payload["archived"] == 1
    assert payload["tracker_archived"] == 1

    rows = (
        await db.execute(select(JobResult).order_by(JobResult.final_score.desc()))
    ).scalars().all()
    assert rows[0].archived_by_llm is True
    assert rows[0].archival_reason == "Job posting is expired or no longer available"
    assert rows[1].archived_by_llm is None

    tracker_row = (await db.execute(select(Application))).scalar_one()
    assert tracker_row.status == "archived"
