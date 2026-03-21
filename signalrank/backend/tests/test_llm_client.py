from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm.openrouter import (
    FALLBACK_MODELS,
    OpenRouterClient,
    _extract_json,
)


def test_extract_json_from_clean():
    raw = '{"skills": ["python", "ml"]}'
    assert _extract_json(raw) == {"skills": ["python", "ml"]}


def test_extract_json_from_markdown_fence():
    raw = '```json\n{"name": "test"}\n```'
    assert _extract_json(raw) == {"name": "test"}


def test_extract_json_from_surrounding_text():
    raw = 'Here is the result: {"ok": true} hope that helps!'
    assert _extract_json(raw) == {"ok": True}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("no json here") is None


def test_fallback_models_has_three():
    assert len(FALLBACK_MODELS) >= 3


def _mock_success_response(content: str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_error_response(status_code: int = 500) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=MagicMock(),
        response=resp,
    )
    return resp


@pytest.mark.asyncio
async def test_client_returns_json_on_success():
    client = OpenRouterClient(api_key="test-key")
    mock_resp = _mock_success_response('{"result": "ok"}')

    with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
        result = await client.llm_json("test prompt")

    assert result == {"result": "ok"}


@pytest.mark.asyncio
async def test_client_returns_error_dict_on_500():
    client = OpenRouterClient(api_key="test-key")
    mock_resp = _mock_error_response(500)

    with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
        result = await client.llm_json("test prompt")

    assert "_error" in result


@pytest.mark.asyncio
async def test_client_text_returns_string():
    client = OpenRouterClient(api_key="test-key")
    mock_resp = _mock_success_response("Hello world")

    with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
        result = await client.llm_text("system", "user msg")

    assert result == "Hello world"


@pytest.mark.asyncio
async def test_client_text_returns_empty_on_failure():
    client = OpenRouterClient(api_key="test-key")
    mock_resp = _mock_error_response(500)

    with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
        result = await client.llm_text("system", "user msg")

    assert result == ""
