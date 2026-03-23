"""Tests for batch.recruiter_finder — no network calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from batch.recruiter_finder import (
    _is_recruiter_title,
    _parse_ddg_html,
    _slug_to_name,
    find_recruiters,
)


# ---------------------------------------------------------------------------
# _slug_to_name
# ---------------------------------------------------------------------------

def test_slug_basic():
    assert _slug_to_name("john-doe") == "John Doe"


def test_slug_strips_hex_suffix():
    assert _slug_to_name("jane-smith-12ab34") == "Jane Smith"


def test_slug_single_part():
    assert _slug_to_name("alice") == "Alice"


def test_slug_empty():
    assert _slug_to_name("") is None


def test_slug_all_numeric_suffix():
    assert _slug_to_name("bob-jones-99887766") == "Bob Jones"


# ---------------------------------------------------------------------------
# _is_recruiter_title
# ---------------------------------------------------------------------------

def test_recruiter_title_positive():
    assert _is_recruiter_title("Senior Technical Recruiter at Google")
    assert _is_recruiter_title("Talent Acquisition Specialist")
    assert _is_recruiter_title("HR Business Partner")


def test_recruiter_title_negative():
    assert not _is_recruiter_title("Software Engineer")
    assert not _is_recruiter_title("Product Manager")


# ---------------------------------------------------------------------------
# _parse_ddg_html
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="https://in.linkedin.com/in/alice-jones-99aa">
    Alice Jones - Senior Recruiter at Adobe, India
  </a>
</div>
<div class="result">
  <a class="result__a" href="https://www.linkedin.com/in/bob-smith">
    Bob Smith - Software Engineer
  </a>
</div>
</body></html>
"""


def test_parse_ddg_extracts_slugs():
    results = _parse_ddg_html(_SAMPLE_HTML)
    slugs = [r["slug"] for r in results]
    assert "alice-jones-99aa" in slugs
    assert "bob-smith" in slugs


def test_parse_ddg_deduplicates():
    results = _parse_ddg_html(_SAMPLE_HTML + _SAMPLE_HTML)
    slugs = [r["slug"] for r in results]
    assert len(slugs) == len(set(slugs))


def test_parse_ddg_empty_html():
    assert _parse_ddg_html("<html></html>") == []


# ---------------------------------------------------------------------------
# find_recruiters — mocked network, no email/domain in output
# ---------------------------------------------------------------------------

_LLM_RESPONSE = [
    {"slug": "alice-jones-99aa", "name": "Alice Jones", "title": "Senior Recruiter at Adobe", "is_recruiter": True},
]


@pytest.mark.asyncio
async def test_find_recruiters_with_llm_enrichment():
    with patch("batch.recruiter_finder._ddg_search_sync", return_value=_SAMPLE_HTML), \
         patch("batch.recruiter_finder._llm_enrich", new_callable=AsyncMock, return_value=_LLM_RESPONSE), \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
        results = await find_recruiters("Adobe", max_results=5)

    assert len(results) == 1
    assert results[0]["name"] == "Alice Jones"
    assert results[0]["linkedin_url"] == "https://www.linkedin.com/in/alice-jones-99aa"
    assert results[0]["source"] == "ddg+llm"
    assert results[0]["confidence"] == "high"
    assert "email" not in results[0]
    assert "domain" not in results[0]


@pytest.mark.asyncio
async def test_find_recruiters_heuristic_fallback_no_api_key():
    with patch("batch.recruiter_finder._ddg_search_sync", return_value=_SAMPLE_HTML), \
         patch.dict("os.environ", {}, clear=True):
        results = await find_recruiters("Adobe", max_results=10)

    assert len(results) == 2
    for r in results:
        assert "email" not in r
        assert "domain" not in r


@pytest.mark.asyncio
async def test_find_recruiters_respects_max_results():
    many = "".join(
        f'<div class="result"><a class="result__a" href="https://www.linkedin.com/in/person-{i}">'
        f'Person {i} - Recruiter at Co India</a></div>'
        for i in range(20)
    )
    html = f"<html><body>{many}</body></html>"
    with patch("batch.recruiter_finder._ddg_search_sync", return_value=html), \
         patch("batch.recruiter_finder._llm_enrich", new_callable=AsyncMock, return_value=[
             {"slug": f"person-{i}", "name": f"Person {i}", "title": "Recruiter", "is_recruiter": True}
             for i in range(20)
         ]):
        results = await find_recruiters("Co", max_results=5)

    assert len(results) <= 5


@pytest.mark.asyncio
async def test_find_recruiters_ddg_error_returns_empty():
    import httpx
    with patch("batch.recruiter_finder._ddg_search_sync", side_effect=httpx.HTTPError("err")), \
         patch("batch.recruiter_finder._llm_enrich", new_callable=AsyncMock, return_value=[]):
        results = await find_recruiters("Adobe", max_results=5)

    assert results == []


@pytest.mark.asyncio
async def test_find_recruiters_india_scope_in_query():
    captured_queries: list[str] = []

    def fake_ddg(query: str) -> str:
        captured_queries.append(query)
        return "<html></html>"

    with patch("batch.recruiter_finder._ddg_search_sync", side_effect=fake_ddg), \
         patch("batch.recruiter_finder._llm_enrich", new_callable=AsyncMock, return_value=[]):
        await find_recruiters("Snowflake", max_results=5)

    assert all("India" in q for q in captured_queries)


@pytest.mark.asyncio
async def test_find_recruiters_uses_ddg_cache():
    """When fresh cache exists, DDG is not called."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock

    cache_row = MagicMock()
    cache_row.raw_candidates = [
        {"slug": "alice-jones-99aa", "snippet": "Alice Jones - Recruiter at Adobe India"},
    ]
    cache_row.searched_at = datetime.now(timezone.utc) - timedelta(days=1)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = cache_row
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    ddg_called = False

    def spy_ddg(query, retries=3):
        nonlocal ddg_called
        ddg_called = True
        return "<html></html>"

    with patch("batch.recruiter_finder._ddg_search_sync", side_effect=spy_ddg), \
         patch("batch.recruiter_finder._llm_enrich", new_callable=AsyncMock, return_value=_LLM_RESPONSE), \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
        results = await find_recruiters("Adobe", max_results=5, db=mock_session)

    assert not ddg_called, "DDG should not be called when cache is fresh"
    assert len(results) >= 1


def test_valid_slug_regex():
    """URL format validation rejects bad slugs."""
    from batch.recruiter_finder import _VALID_SLUG_RE
    assert _VALID_SLUG_RE.match("john-doe-123abc")
    assert _VALID_SLUG_RE.match("alice")
    assert not _VALID_SLUG_RE.match("")
    assert not _VALID_SLUG_RE.match("-invalid")
    assert not _VALID_SLUG_RE.match("a" * 200)
    assert not _VALID_SLUG_RE.match("has spaces")
    assert not _VALID_SLUG_RE.match("UPPERCASE")
