import asyncio
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


def test_fallback_models_has_at_least_two():
    assert len(FALLBACK_MODELS) >= 2


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


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """Reset module-level probe cache before each test to prevent state leaks."""
    import llm.openrouter as mod
    mod._probe_cache.clear()
    mod._probe_cache_at.clear()
    mod._probe_locks.clear()
    yield
    mod._probe_cache.clear()
    mod._probe_cache_at.clear()
    mod._probe_locks.clear()


@pytest.mark.asyncio
async def test_probe_models_caches_healthy():
    """probe_models sends a tiny prompt to each model, caches healthy ones."""
    import llm.openrouter as mod

    client = OpenRouterClient(api_key="test-key", models=["model-a", "model-b", "model-c"])

    async def fake_post(*args, **kwargs):
        model = kwargs.get("json", {}).get("model", "")
        if model == "model-b":
            raise httpx.HTTPError("dead")
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        resp.raise_for_status = MagicMock()
        return resp

    with patch.object(client._http, "post", AsyncMock(side_effect=fake_post)):
        healthy = await client.probe_models()

    assert "model-a" in healthy
    assert "model-b" not in healthy
    assert "model-c" in healthy
    assert mod._probe_cache[tuple(client.models)] == healthy


@pytest.mark.asyncio
async def test_probe_models_uses_lock_no_thundering_herd():
    """Concurrent _ensure_healthy calls should only trigger one probe."""
    client = OpenRouterClient(api_key="test-key", models=["model-a"])

    mock_resp = _mock_success_response("hi")
    mock_post = AsyncMock(return_value=mock_resp)

    with patch.object(client._http, "post", mock_post):
        results = await asyncio.gather(
            client._ensure_healthy(),
            client._ensure_healthy(),
            client._ensure_healthy(),
        )

    assert all(r == ["model-a"] for r in results)
    assert mock_post.call_count == 1, f"Expected 1 probe call, got {mock_post.call_count}"
