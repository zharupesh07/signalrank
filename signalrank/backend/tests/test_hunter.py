"""Tests for batch.hunter — Hunter.io API client (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from batch.hunter import EmailResult, HunterClient


@pytest.fixture
def client():
    return HunterClient(api_key="test-key")


@pytest.fixture
def no_key_client():
    return HunterClient(api_key="")


# ---------------------------------------------------------------------------
# HunterClient.available
# ---------------------------------------------------------------------------

def test_available_with_key(client):
    assert client.available is True


def test_not_available_without_key(no_key_client):
    assert no_key_client.available is False


# ---------------------------------------------------------------------------
# find_email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_email_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "email": "alice.jones@adobe.com",
            "score": 92,
            "type": "personal",
            "first_name": "Alice",
            "last_name": "Jones",
            "position": "Senior Recruiter",
            "sources": [{"domain": "adobe.com"}],
        }
    }
    mock_resp.raise_for_status = MagicMock()

    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=mock_resp)

    result = await client.find_email("adobe.com", "Alice Jones")
    assert result is not None
    assert result.email == "alice.jones@adobe.com"
    assert result.confidence == 92
    assert result.type == "personal"
    assert result.position == "Senior Recruiter"
    assert result.sources == 1


@pytest.mark.asyncio
async def test_find_email_low_confidence_skipped(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"email": "maybe@co.com", "score": 20, "type": "personal", "sources": []}
    }
    mock_resp.raise_for_status = MagicMock()

    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=mock_resp)

    result = await client.find_email("co.com", "Maybe Person")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_no_result(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"email": None, "score": 0}}
    mock_resp.raise_for_status = MagicMock()

    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=mock_resp)

    result = await client.find_email("unknown.com", "Nobody Here")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_single_name_returns_none(client):
    result = await client.find_email("co.com", "Alice")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_no_api_key(no_key_client):
    result = await no_key_client.find_email("co.com", "Alice Jones")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_rate_limit(client):
    resp = httpx.Response(429, request=httpx.Request("GET", "https://api.hunter.io/v2/email-finder"))
    client._http = AsyncMock()
    client._http.get = AsyncMock(side_effect=httpx.HTTPStatusError("rate limit", request=resp.request, response=resp))

    result = await client.find_email("co.com", "Alice Jones")
    assert result is None


@pytest.mark.asyncio
async def test_find_email_network_error(client):
    client._http = AsyncMock()
    client._http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    result = await client.find_email("co.com", "Alice Jones")
    assert result is None


# ---------------------------------------------------------------------------
# domain_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_domain_search_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "emails": [
                {"value": "alice@adobe.com", "confidence": 90, "type": "personal",
                 "first_name": "Alice", "last_name": "Jones", "position": "Recruiter",
                 "sources": [{"domain": "adobe.com"}]},
                {"value": "bob@adobe.com", "confidence": 80, "type": "personal",
                 "first_name": "Bob", "last_name": "Smith", "position": "HR",
                 "sources": []},
            ]
        }
    }
    mock_resp.raise_for_status = MagicMock()

    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=mock_resp)

    results = await client.domain_search("adobe.com", limit=5)
    assert len(results) == 2
    assert results[0].email == "alice@adobe.com"
    assert results[1].email == "bob@adobe.com"


@pytest.mark.asyncio
async def test_domain_search_no_key(no_key_client):
    results = await no_key_client.domain_search("co.com")
    assert results == []


@pytest.mark.asyncio
async def test_domain_search_error(client):
    client._http = AsyncMock()
    client._http.get = AsyncMock(side_effect=httpx.ConnectError("fail"))

    results = await client.domain_search("co.com")
    assert results == []
