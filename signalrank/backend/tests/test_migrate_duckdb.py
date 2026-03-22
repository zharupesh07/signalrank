from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scripts.migrate_duckdb_jobs import clean_jobs, validate_jobs


def _job(**kwargs) -> dict:
    base = {
        "job_url": "https://example.com/1",
        "title": "ML Engineer",
        "company": "Acme",
        "description": "A" * 50,
        "location": "Bangalore",
        "site": "indeed",
        "date_posted": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "ingested_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
    }
    base.update(kwargs)
    return base


# --- clean_jobs ---

def test_clean_strips_whitespace():
    jobs = clean_jobs([_job(title="  ML Engineer  ", company=" Acme ", location=" Pune ")])
    assert jobs[0]["title"] == "ML Engineer"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["location"] == "Pune"


def test_clean_skips_empty_url():
    jobs = clean_jobs([_job(job_url=""), _job(job_url="   ")])
    assert jobs == []


def test_clean_none_fields_become_none():
    jobs = clean_jobs([_job(title=None, company=None, location=None)])
    assert jobs[0]["title"] is None
    assert jobs[0]["company"] is None
    assert jobs[0]["location"] is None


def test_clean_bogus_date_before_2000_set_to_none():
    jobs = clean_jobs([_job(date_posted=datetime(1992, 3, 5))])
    assert jobs[0]["date_posted"] is None


def test_clean_naive_datetime_gets_utc():
    naive = datetime(2025, 6, 1)
    jobs = clean_jobs([_job(date_posted=naive)])
    assert jobs[0]["date_posted"].tzinfo is not None
    assert jobs[0]["date_posted"].tzinfo == timezone.utc


def test_clean_aware_datetime_unchanged():
    aware = datetime(2025, 6, 1, tzinfo=timezone.utc)
    jobs = clean_jobs([_job(date_posted=aware)])
    assert jobs[0]["date_posted"] == aware


def test_clean_none_ingested_at_becomes_now():
    jobs = clean_jobs([_job(ingested_at=None)])
    assert jobs[0]["ingested_at"] is not None
    assert jobs[0]["ingested_at"].tzinfo is not None


def test_clean_naive_ingested_at_gets_utc():
    jobs = clean_jobs([_job(ingested_at=datetime(2025, 1, 1))])
    assert jobs[0]["ingested_at"].tzinfo == timezone.utc


def test_clean_multiple_jobs():
    raw = [_job(job_url=f"https://x.com/{i}") for i in range(5)]
    jobs = clean_jobs(raw)
    assert len(jobs) == 5


# --- validate_jobs ---

def test_validate_passes_clean_jobs():
    jobs = clean_jobs([_job(job_url="https://x.com/1"), _job(job_url="https://x.com/2")])
    assert validate_jobs(jobs) == []


def test_validate_catches_duplicate_url():
    jobs = [_job(job_url="https://x.com/1"), _job(job_url="https://x.com/1")]
    errors = validate_jobs(jobs)
    assert any("duplicate" in e for e in errors)


def test_validate_catches_missing_url():
    jobs = [{"job_url": "", "description": "A" * 50}]
    errors = validate_jobs(jobs)
    assert any("missing job_url" in e for e in errors)


def test_validate_catches_short_description():
    jobs = [_job(description="short")]
    errors = validate_jobs(jobs)
    assert any("description too short" in e for e in errors)


# --- date filter (1 month) ---

def test_clean_filters_old_jobs():
    """Jobs older than 30 days should be filtered out by the caller (read_duckdb_jobs SQL).
    clean_jobs itself does not filter by recency — that's done in SQL.
    Bogus pre-2000 dates are nulled, valid old dates pass through."""
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    jobs = clean_jobs([_job(date_posted=old)])
    # clean_jobs keeps the job, only nulls dates < 2000
    assert len(jobs) == 1
    assert jobs[0]["date_posted"] == old
