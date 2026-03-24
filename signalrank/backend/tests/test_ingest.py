"""Tests for api/routes/ingest.py — no real network or LLM calls."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta

from api.routes.ingest import _parse_ingest_response, _compute_priority

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
