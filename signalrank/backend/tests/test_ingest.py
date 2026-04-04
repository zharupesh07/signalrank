"""Tests for api/routes/ingest.py — no real network or LLM calls."""
from __future__ import annotations
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from api.models import JobRaw
import api.routes.ingest as ingest_route
from api.routes.ingest import _parse_ingest_response, _compute_priority, _validate_url, ingest_extract, IngestRequest
from fastapi import HTTPException

@pytest.fixture
async def auth_token(client):
    await client.post("/api/auth/register", json={"email": "ingest@test.com", "password": "password123"})
    r = await client.post("/api/auth/login", json={"email": "ingest@test.com", "password": "password123"})
    return r.json()["access_token"]


LLM_RESPONSE = """TITLE: Senior ML Engineer
COMPANY: Acme Corp
LOCATION: Bangalore, India
JOB_URL: https://acme.com/jobs/123
DATE_POSTED: 2026-03-23
DESCRIPTION: Build ML platform at scale."""

def test_parse_full_response():
    result = _parse_ingest_response(LLM_RESPONSE)
    assert result["title"] == "Senior ML Engineer"
    assert result["company"] == "Acme Corp"
    assert result["location"] == "Bangalore, India"
    assert result["job_url"] == "https://acme.com/jobs/123"
    assert result["date_posted"] == "2026-03-23"
    assert "ML platform" in result["description"]

def test_parse_missing_fields():
    result = _parse_ingest_response("TITLE: Engineer\nCOMPANY: Corp")
    assert result["title"] == "Engineer"
    assert result["company"] == "Corp"
    assert result["location"] == ""
    assert result["job_url"] == ""
    assert result["date_posted"] == ""

def test_parse_empty_response():
    result = _parse_ingest_response("")
    assert result["title"] == ""

def test_priority_fresh_job():
    posted = datetime.now(timezone.utc) - timedelta(hours=10)
    assert _compute_priority(posted, None) == "P1"

def test_priority_old_job_ss_tier():
    posted = datetime.now(timezone.utc) - timedelta(hours=100)
    assert _compute_priority(posted, "SS") == "P1"

def test_priority_old_job_s_tier():
    posted = datetime.now(timezone.utc) - timedelta(hours=60)
    assert _compute_priority(posted, "S") == "P1"

def test_priority_old_job_a_tier():
    posted = datetime.now(timezone.utc) - timedelta(hours=60)
    assert _compute_priority(posted, "A") == "P2"

def test_priority_no_date_defaults_p1():
    assert _compute_priority(None, None) == "P1"

def test_priority_no_date_with_b_tier():
    assert _compute_priority(None, "B") == "P1"


def test_validate_url_accepts_https():
    _validate_url("https://example.com/jobs/123")


def test_validate_url_rejects_non_http():
    with pytest.raises(HTTPException):
        _validate_url("ftp://example.com")


def test_validate_url_rejects_localhost():
    with pytest.raises(HTTPException):
        _validate_url("http://localhost:8000/internal")


def test_validate_url_rejects_loopback_ip():
    with pytest.raises(HTTPException):
        _validate_url("http://127.0.0.1/secret")


@pytest.mark.asyncio
async def test_ingest_extract_uses_structured_schema_output():
    llm = AsyncMock()
    llm.llm_json.return_value = {
        "title": "Senior ML Engineer",
        "company": "Acme Corp",
        "location": "Bangalore, India",
        "job_url": "https://acme.com/jobs/123",
        "date_posted": "2026-03-23",
        "description": "Build ML platform at scale.",
    }

    result = await ingest_extract(
        IngestRequest(text="ML engineer role"),
        current_user=SimpleNamespace(id="user-1"),
        llm=llm,
    )

    assert result.title == "Senior ML Engineer"
    called_kwargs = llm.llm_json.await_args.kwargs
    assert called_kwargs["schema_name"] == "job_ingest_extract"
    assert called_kwargs["json_schema"]["required"] == [
        "title",
        "company",
        "location",
        "job_url",
        "date_posted",
        "description",
    ]


@pytest.mark.asyncio
async def test_ingest_confirm_persists_job_profile(client, auth_token, db):
    response = await client.post(
        "/api/jobs/ingest/confirm",
        json={
            "title": "Senior ML Engineer",
            "company": "Acme Corp",
            "location": "Remote",
            "job_url": "https://example.com/jobs/123",
            "date_posted": "2026-03-23",
            "description": "Build ML infrastructure with Python and Kubernetes.",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200

    job = (await db.execute(select(JobRaw).where(JobRaw.job_url == "https://example.com/jobs/123"))).scalar_one()
    assert job.job_profile["role_family"] == "AI / ML"
    assert job.job_profile["work_mode"] == "remote"


@pytest.mark.asyncio
async def test_ingest_confirm_reuses_existing_job_profile_across_users(client, db, monkeypatch):
    await client.post("/api/auth/register", json={"email": "reuse-1@test.com", "password": "password123"})
    token_1 = (
        await client.post("/api/auth/login", json={"email": "reuse-1@test.com", "password": "password123"})
    ).json()["access_token"]
    await client.post("/api/auth/register", json={"email": "reuse-2@test.com", "password": "password123"})
    token_2 = (
        await client.post("/api/auth/login", json={"email": "reuse-2@test.com", "password": "password123"})
    ).json()["access_token"]

    calls: list[dict] = []
    original_build = ingest_route.build_job_profile

    def _tracking_build_job_profile(**kwargs):
        calls.append(kwargs)
        return original_build(**kwargs)

    monkeypatch.setattr(ingest_route, "build_job_profile", _tracking_build_job_profile)

    payload = {
        "title": "Senior ML Engineer",
        "company": "Acme Corp",
        "location": "Remote",
        "job_url": "https://example.com/jobs/reuse",
        "date_posted": "2026-03-23",
        "description": "Build ML infrastructure with Python and Kubernetes.",
    }

    first = await client.post("/api/jobs/ingest/confirm", json=payload, headers={"Authorization": f"Bearer {token_1}"})
    second = await client.post("/api/jobs/ingest/confirm", json=payload, headers={"Authorization": f"Bearer {token_2}"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1

    jobs = (await db.execute(select(JobRaw).where(JobRaw.job_url == payload["job_url"]))).scalar_one()
    assert jobs.job_profile["job_fingerprint"]
