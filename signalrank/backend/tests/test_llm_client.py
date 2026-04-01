import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from llm.openrouter import (
    FALLBACK_MODELS,
    OpenRouterClient,
    _extract_json,
    _looks_like_nonempty_resume_payload,
    _extract_response_content,
    fetch_free_vision_models,
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


def test_extract_json_repairs_trailing_commas():
    raw = '{"name": "test", "skills": ["python",],}'
    assert _extract_json(raw) == {"name": "test", "skills": ["python"]}


def test_extract_json_handles_fenced_json_without_closing_fence():
    raw = '```json\n{"name":"test","skills":["python",],}\n'
    assert _extract_json(raw) == {"name": "test", "skills": ["python"]}


def test_extract_response_content_handles_multiple_payload_shapes():
    assert _extract_response_content({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    assert _extract_response_content({"choices": [{"message": {"content": [{"type": "text", "text": "hello"}]}}]}) == "hello"
    assert _extract_response_content({"choices": [{"text": "hello"}]}) == "hello"
    assert _extract_response_content({"content": "hello"}) == "hello"
    assert _extract_response_content({"output": [{"content": "hello"}]}) == "hello"


def test_fallback_models_has_at_least_two():
    assert len(FALLBACK_MODELS) >= 2


def test_nonempty_resume_payload_detects_empty_and_filled_dicts():
    assert not _looks_like_nonempty_resume_payload({"name": "", "experiences": [], "skills": []})
    assert _looks_like_nonempty_resume_payload({"name": "Example"})
    assert _looks_like_nonempty_resume_payload({"experiences": [{"title": "Engineer"}]})


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


@pytest.mark.asyncio
async def test_client_tolerates_non_choices_payload_shape():
    client = OpenRouterClient(api_key="test-key")
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"content": '{"result":"ok"}'}
    resp.text = '{"result":"ok"}'
    resp.raise_for_status = MagicMock()

    with patch.object(client._http, "post", AsyncMock(return_value=resp)):
        result = await client.llm_json("test prompt")

    assert result == {"result": "ok"}


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """Reset module-level probe cache before each test to prevent state leaks."""
    import llm.openrouter as mod
    mod._response_cache.clear()
    mod._probe_cache.clear()
    mod._probe_cache_at.clear()
    mod._probe_locks.clear()
    yield
    mod._response_cache.clear()
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


@pytest.mark.asyncio
async def test_fetch_free_vision_models_filters_and_sorts():
    client = AsyncMock()
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "data": [
            {"id": "google/gemma-3-4b-it:free", "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "google/gemma-3-27b-it:free", "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "nvidia/nemotron-nano-12b-v2-vl:free", "architecture": {"input_modalities": ["image", "text"]}},
            {"id": "openai/gpt-4.1-mini", "architecture": {"input_modalities": ["text", "image"]}},
            {"id": "text-only-free:free", "architecture": {"input_modalities": ["text"]}},
        ]
    }
    client.get.return_value = response

    models = await fetch_free_vision_models("test-key", client)

    assert models == [
        "google/gemma-3-27b-it:free",
        "nvidia/nemotron-nano-12b-v2-vl:free",
        "google/gemma-3-4b-it:free",
    ]
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_free_vision_models_falls_back_on_error():
    client = AsyncMock()
    client.get.side_effect = httpx.HTTPError("boom")

    models = await fetch_free_vision_models("test-key", client)

    assert models


@pytest.mark.asyncio
async def test_llm_json_vision_discovers_models_when_none_supplied():
    client = OpenRouterClient(api_key="test-key", models=["unused"])

    with patch("llm.openrouter.fetch_free_vision_models", AsyncMock(return_value=["vision-a"])) as mock_fetch, patch.object(
        client, "_call", AsyncMock(return_value='{"name":"Vision User"}')
    ) as mock_call:
        result = await client.llm_json_vision([b"png-bytes"], "Parse it")

    assert result == {"name": "Vision User"}
    mock_fetch.assert_awaited_once()
    assert mock_call.await_args.args[0] == "vision-a"


@pytest.mark.asyncio
async def test_llm_json_vision_skips_structurally_empty_resume_payload():
    client = OpenRouterClient(api_key="test-key", models=["unused"])

    with patch.object(
        client,
        "_call",
        AsyncMock(side_effect=['{"name":"","experiences":[],"skills":[]}', '{"name":"Vision User"}']),
    ) as mock_call:
        result = await client.llm_json_vision([b"png-bytes"], "Parse it", vision_models=["vision-a", "vision-b"])

    assert result == {"name": "Vision User"}
    assert mock_call.await_count == 2


def test_response_cache_eviction_keeps_most_recent_entries():
    import llm.openrouter as mod

    old_cache_max = mod._RESPONSE_CACHE_MAX
    mod._response_cache.clear()
    mod._RESPONSE_CACHE_MAX = 2
    try:
        mod._store_response_cache_value("a", {"ok": 1})
        mod._store_response_cache_value("b", {"ok": 2})
        mod._store_response_cache_value("c", {"ok": 3})

        assert "a" not in mod._response_cache
        assert list(mod._response_cache.keys()) == ["b", "c"]
        assert mod._get_response_cache_value("b") == {"ok": 2}
        assert list(mod._response_cache.keys()) == ["c", "b"]
    finally:
        mod._RESPONSE_CACHE_MAX = old_cache_max
        mod._response_cache.clear()
