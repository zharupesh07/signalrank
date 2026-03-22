from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from batch.sources.rapidapi import _normalize_results, _parse_date, search
from batch.query_builder import SearchQuery
from batch.scraper import ScraperConfig


# --- _parse_date ---

def test_parse_date_none():
    assert _parse_date(None) is None


def test_parse_date_empty_string():
    assert _parse_date("") is None


def test_parse_date_iso():
    result = _parse_date("2024-01-15T10:00:00Z")
    assert isinstance(result, datetime)
    assert result.year == 2024


def test_parse_date_already_datetime():
    dt = datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert _parse_date(dt) == dt


def test_parse_date_garbage():
    assert _parse_date("not-a-date") is None


# --- _normalize_results ---

def test_normalize_list_format():
    data = [
        {"job_url": "https://example.com/1", "title": "ML Engineer", "company": "Acme",
         "description": "Great job", "location": "Bangalore"},
    ]
    jobs = _normalize_results("jsearch", data)
    assert len(jobs) == 1
    assert jobs[0].job_url == "https://example.com/1"
    assert jobs[0].title == "ML Engineer"
    assert jobs[0].site == "jsearch"


def test_normalize_dict_with_data_key():
    data = {"data": [
        {"job_url": "https://example.com/2", "title": "Data Scientist", "company": "Corp",
         "description": "Cool role", "location": "Mumbai"},
    ]}
    jobs = _normalize_results("linkedin", data)
    assert len(jobs) == 1
    assert jobs[0].company == "Corp"


def test_normalize_dict_with_results_key():
    data = {"results": [
        {"url": "https://example.com/3", "title": "Engineer"},
    ]}
    jobs = _normalize_results("indeed", data)
    assert len(jobs) == 1
    assert jobs[0].job_url == "https://example.com/3"


def test_normalize_skips_items_without_url():
    data = [
        {"title": "No URL Job", "description": "desc"},
        {"job_url": "https://example.com/valid", "title": "Valid"},
    ]
    jobs = _normalize_results("test", data)
    assert len(jobs) == 1
    assert jobs[0].job_url == "https://example.com/valid"


def test_normalize_alternate_field_names():
    data = [
        {
            "job_apply_link": "https://example.com/apply",
            "job_title": "Senior ML",
            "employer_name": "BigCo",
            "job_description": "Long description here",
            "job_city": "Pune",
            "job_posted_at_datetime_utc": "2024-02-01T00:00:00Z",
        }
    ]
    jobs = _normalize_results("jsearch", data)
    assert len(jobs) == 1
    assert jobs[0].title == "Senior ML"
    assert jobs[0].company == "BigCo"
    assert jobs[0].location == "Pune"


def test_normalize_empty_list():
    assert _normalize_results("test", []) == []


def test_normalize_empty_dict():
    assert _normalize_results("test", {}) == []


def test_normalize_unknown_structure():
    assert _normalize_results("test", "not-a-dict-or-list") == []


# --- search skips when no API key ---

@pytest.mark.asyncio
async def test_search_skips_without_key():
    config = ScraperConfig(rapidapi_key=None)
    queries = [SearchQuery(term="ML Engineer", location="", country="India")]
    result = await search(queries, config)
    assert result == []
