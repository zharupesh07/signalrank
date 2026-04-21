import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import time as _time
from collections import OrderedDict
from copy import deepcopy

import httpx

from api.config import settings

logger = logging.getLogger(__name__)

_response_cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
_RESPONSE_TTL = 86400  # 24h — same prompt+temp = same result
_RESPONSE_CACHE_MAX = settings.llm_response_cache_max

_probe_cache: dict[tuple, list[str]] = {}
_probe_cache_at: dict[tuple, float] = {}
_probe_locks: dict[tuple, asyncio.Lock] = {}
_PROBE_TTL = 3600  # 1 hour


def _get_probe_lock(key: tuple) -> asyncio.Lock:
    if key not in _probe_locks:
        _probe_locks[key] = asyncio.Lock()
    return _probe_locks[key]


def _get_response_cache_value(cache_key: str):
    cached = _response_cache.get(cache_key)
    if not cached:
        return None
    if (_time.monotonic() - cached[0]) >= _RESPONSE_TTL:
        _response_cache.pop(cache_key, None)
        return None
    _response_cache.move_to_end(cache_key)
    return cached[1]


def _store_response_cache_value(cache_key: str, value: object) -> None:
    if _RESPONSE_CACHE_MAX <= 0:
        return
    _response_cache[cache_key] = (_time.monotonic(), value)
    _response_cache.move_to_end(cache_key)
    while len(_response_cache) > _RESPONSE_CACHE_MAX:
        _response_cache.popitem(last=False)

FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "arcee-ai/trinity-large-preview:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-3-4b-it:free",
]

# Keep text parsing on the fastest reliable free models by default.
FAST_TEXT_MODELS = FALLBACK_MODELS[:3]

# Free vision-capable models on OpenRouter, in preference order.
# Updated by fetch_free_vision_models() at runtime; this is the static fallback.
VISION_MODELS = [
    "google/gemma-3-27b-it:free",                # 2.3s, 27B — best quality
    "google/gemma-3-12b-it:free",                # 6.0s, 12B
    "nvidia/nemotron-nano-12b-v2-vl:free",       # 2.0s, 12B — dedicated VL
    "google/gemma-3-4b-it:free",                 # 2.2s, 4B — fast fallback
]

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
MAX_RETRIES_PER_MODEL = 3
_llm_semaphore = asyncio.Semaphore(max(1, int(getattr(settings, "llm_semaphore", 3))))


_MODEL_SIZE_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)b")
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.I | re.S)


def _repair_jsonish(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _try_json_loads(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError:
            return None


def _extract_json(raw: str) -> dict | None:
    text = raw.strip()
    candidates: list[str] = []
    fenced = _FENCED_JSON_RE.findall(text)
    if fenced:
        candidates.extend(block.strip() for block in fenced if block.strip())
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
        if stripped:
            candidates.append(stripped)
    candidates.append(text)

    for candidate in candidates:
        parsed = _try_json_loads(candidate)
        if parsed is not None:
            return parsed
        repaired_candidate = _repair_jsonish(candidate)
        if repaired_candidate != candidate:
            parsed = _try_json_loads(repaired_candidate)
            if parsed is not None:
                return parsed
        auto_closed = _auto_close_jsonish(repaired_candidate)
        if auto_closed != repaired_candidate:
            parsed = _try_json_loads(auto_closed)
            if parsed is not None:
                return parsed

        for nested in _extract_json_objects(candidate):
            parsed = _try_json_loads(nested)
            if parsed is not None:
                return parsed
            repaired_nested = _repair_jsonish(nested)
            if repaired_nested != nested:
                parsed = _try_json_loads(repaired_nested)
                if parsed is not None:
                    return parsed
            auto_closed_nested = _auto_close_jsonish(repaired_nested)
            if auto_closed_nested != repaired_nested:
                parsed = _try_json_loads(auto_closed_nested)
                if parsed is not None:
                    return parsed

    return None


def _extract_json_objects(text: str) -> list[str]:
    stack = 0
    start_idx = None
    in_string = False
    escape = False
    candidates: list[str] = []

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if stack == 0:
                start_idx = idx
            stack += 1
            continue
        if ch == "}" and stack > 0:
            stack -= 1
            if stack == 0 and start_idx is not None:
                candidates.append(text[start_idx : idx + 1])

    return list(reversed(candidates))


def _auto_close_jsonish(text: str) -> str:
    brace_balance = 0
    bracket_balance = 0
    in_string = False
    escape = False

    for ch in text:
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            brace_balance += 1
        elif ch == "}" and brace_balance > 0:
            brace_balance -= 1
        elif ch == "[":
            bracket_balance += 1
        elif ch == "]" and bracket_balance > 0:
            bracket_balance -= 1

    if in_string:
        text += '"'
    if bracket_balance > 0:
        text += "]" * bracket_balance
    if brace_balance > 0:
        text += "}" * brace_balance
    return text


def _looks_like_nonempty_resume_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("name", "email", "phone", "location", "position", "summary"):
        if str(payload.get(key) or "").strip():
            return True
    for key in ("experiences", "skills", "projects", "education", "certifications"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value:
            return True
    return False


def _coerce_content_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        joined = "".join(parts).strip()
        return joined or None
    if isinstance(value, dict):
        for key in ("text", "content", "output_text"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def _extract_response_content(payload) -> str | None:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return None

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = _coerce_content_text(message.get("content"))
                if content:
                    return content
            content = _coerce_content_text(first.get("text"))
            if content:
                return content
            content = _coerce_content_text(first.get("content"))
            if content:
                return content

    message = payload.get("message")
    if isinstance(message, dict):
        content = _coerce_content_text(message.get("content"))
        if content:
            return content

    for key in ("content", "text", "output_text", "response"):
        content = _coerce_content_text(payload.get(key))
        if content:
            return content

    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            content = _coerce_content_text(item)
            if content:
                return content

    return None


def _build_response_format(
    json_schema: dict,
    *,
    schema_name: str = "structured_output",
    strict: bool = True,
) -> dict:
    schema = deepcopy(json_schema)
    if isinstance(schema, dict):
        schema.setdefault("additionalProperties", False)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "strict": strict,
            "schema": schema,
        },
    }


async def fetch_free_vision_models(api_key: str, http: httpx.AsyncClient | None = None) -> list[str]:
    """Query /models, return IDs of free models that accept image input.

    Sorted largest-first (by parameter count in ID, rough heuristic) so the
    most capable model is tried first.  Falls back to VISION_MODELS on error.
    """
    own_http = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(
            MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        models = resp.json().get("data", [])
        free_vision = []
        for m in models:
            if ":free" not in m.get("id", ""):
                continue
            arch = m.get("architecture", {})
            modalities = arch.get("input_modalities", []) or []
            if "image" in modalities:
                free_vision.append(m["id"])
        free_vision.sort(key=_vision_model_sort_key, reverse=True)
        logger.info("Found %d free vision-capable models on OpenRouter", len(free_vision))
        return free_vision if free_vision else VISION_MODELS
    except Exception as exc:
        logger.warning("Could not fetch free vision models: %s — using static list", exc)
        return VISION_MODELS
    finally:
        if own_http:
            await client.aclose()


def _vision_model_sort_key(model_id: str) -> tuple[float, int, str]:
    match = _MODEL_SIZE_RE.search(model_id or "")
    size_hint = float(match.group(1)) if match else 0.0
    multimodal_bonus = 1 if "vl" in (model_id or "").lower() else 0
    return (size_hint, multimodal_bonus, model_id)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        models: list[str] | None = None,
        preferred_models: list[str] | None = None,
        timeout: float = 90.0,
    ):
        self.api_key = api_key
        self.models = models or FAST_TEXT_MODELS
        self.preferred_models = preferred_models or []
        self._http = httpx.AsyncClient(timeout=timeout)

    async def probe_models(self, *, limit: int | None = None) -> list[str]:
        """Probe models concurrently; cache and return healthy ones.

        When limit is set, only the first N models are probed. This keeps the
        common text-parsing path from spending time on low-priority fallbacks.
        """
        models = self.models[:limit] if limit else self.models
        key = tuple(models)

        async def _try(model: str) -> str | None:
            try:
                resp = await self._http.post(
                    BASE_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "HTTP-Referer": "https://signalrank.app",
                        "X-Title": "SignalRank",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Say hi"}],
                        "max_tokens": 5,
                        "temperature": 0.0,
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                return model
            except Exception:
                return None

        results = await asyncio.gather(*[_try(m) for m in models])
        healthy = [m for m in results if m is not None]
        _probe_cache[key] = healthy
        _probe_cache_at[key] = _time.monotonic()
        if not healthy:
            logger.warning("Probe: all %d models failed, will use full list as fallback", len(models))
        else:
            logger.info("Probe found %d/%d healthy models: %s", len(healthy), len(models), healthy)
        return healthy

    async def _ensure_healthy(self, *, limit: int | None = None) -> list[str]:
        """Return cached healthy models for the requested model slice."""
        models = self.models[:limit] if limit else self.models
        key = tuple(models)
        if key in _probe_cache and (_time.monotonic() - _probe_cache_at.get(key, 0)) < _PROBE_TTL:
            return _probe_cache[key]

        lock = _get_probe_lock(key)
        async with lock:
            if key in _probe_cache and (_time.monotonic() - _probe_cache_at.get(key, 0)) < _PROBE_TTL:
                return _probe_cache[key]
            return await self.probe_models(limit=limit)

    async def _call(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        *,
        extra_body: dict | None = None,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> str | None:
        async with _llm_semaphore:
            return await self._call_inner(
                model,
                messages,
                max_tokens,
                temperature,
                extra_body=extra_body,
                request_timeout=request_timeout,
                max_retries=max_retries,
            )

    async def _call_inner(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        *,
        extra_body: dict | None = None,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> str | None:
        retries = MAX_RETRIES_PER_MODEL if max_retries is None else max(0, max_retries)
        for attempt in range(retries + 1):
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if extra_body:
                    payload.update(extra_body)
                resp = await self._http.post(
                    BASE_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "HTTP-Referer": "https://signalrank.app",
                        "X-Title": "SignalRank",
                    },
                    json=payload,
                    timeout=request_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = _extract_response_content(data)
                if content:
                    return content.strip()
                raw_text = resp.text.strip()
                if raw_text:
                    return raw_text
                logger.warning(
                    "Response from %s had no extractable content keys: %s",
                    model,
                    sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
                )
                return None

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        sleep_time = float(retry_after) + random.uniform(0.5, 2.0)
                    else:
                        sleep_time = min(2 ** (attempt + 2), 60) + random.uniform(0.5, 3.0)
                    logger.warning("Rate limited on %s, sleeping %.1fs (attempt %d)", model, sleep_time, attempt)
                    await asyncio.sleep(sleep_time)
                    continue
                if e.response.status_code in (401, 403):
                    logger.error("Auth failed for %s: %s", model, e)
                    return None
                logger.warning("HTTP %d from %s: %s", e.response.status_code, model, e)
                return None

            except Exception as e:
                logger.warning("Error calling %s: %s", model, e)
                return None

        return None

    def _cache_key(
        self,
        messages: list[dict],
        temperature: float,
        extra_body: dict | None = None,
    ) -> str:
        blob = json.dumps(
            {
                "messages": messages,
                "temperature": temperature,
                "models": self.models,
                "extra_body": extra_body or {},
            },
            sort_keys=True,
        )
        return hashlib.md5(blob.encode()).hexdigest()

    async def llm_json(
        self,
        prompt: str | None = None,
        *,
        system: str | None = None,
        user: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: dict | None = None,
        schema_name: str = "structured_output",
        strict: bool = True,
    ) -> dict:
        if system and user:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        else:
            messages = [{"role": "user", "content": prompt or ""}]

        schema_body = None
        if json_schema:
            schema_body = {
                "response_format": _build_response_format(
                    json_schema,
                    schema_name=schema_name,
                    strict=strict,
                )
            }

        cache_key = self._cache_key(messages, temperature, schema_body)
        cached = _get_response_cache_value(cache_key)
        if cached is not None:
            logger.info("llm_json cache hit")
            return cached  # type: ignore[return-value]

        healthy = await self._ensure_healthy(limit=3)
        if healthy:
            models_to_try = healthy + [model for model in self.models if model not in healthy]
        else:
            models_to_try = list(self.models)
        if self.preferred_models:
            preferred = [m for m in self.preferred_models if m in models_to_try]
            if preferred:
                models_to_try = preferred + [m for m in models_to_try if m not in preferred]

        last_error = None
        for model in models_to_try:
            raw = await self._call(
                model,
                messages,
                max_tokens,
                temperature,
                extra_body=schema_body,
            )
            if raw is None and schema_body:
                logger.info("Structured response unavailable on %s, falling back to prompt-only JSON", model)
                raw = await self._call(model, messages, max_tokens, temperature)
            elif schema_body:
                parsed = _extract_json(raw)
                if parsed is not None:
                    logger.info("llm_json success via %s", model)
                    _store_response_cache_value(cache_key, parsed)
                    return parsed
                logger.warning("Non-JSON from %s with structured output: %s...", model, raw[:80])
                logger.info("Retrying %s without structured response format", model)
                raw = await self._call(model, messages, max_tokens, temperature)
            if raw is None:
                last_error = f"{model} returned nothing"
                continue

            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info("llm_json success via %s", model)
                _store_response_cache_value(cache_key, parsed)
                return parsed

            last_error = f"{model} returned non-JSON: {raw[:100]}"
            logger.warning("Non-JSON from %s: %s...", model, raw[:80])

        return {"_error": "llm_failed", "_details": str(last_error)}

    async def llm_text(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        cache_key = self._cache_key(messages, temperature)
        cached = _get_response_cache_value(cache_key)
        if cached is not None:
            logger.info("llm_text cache hit")
            return cached  # type: ignore[return-value]

        healthy = await self._ensure_healthy(limit=3)
        models_to_try = healthy if healthy else self.models[:3]
        if self.preferred_models:
            preferred = [m for m in self.preferred_models if m in models_to_try]
            if preferred:
                models_to_try = preferred

        for model in models_to_try:
            raw = await self._call(model, messages, max_tokens, temperature)
            if raw is not None:
                logger.info("llm_text success via %s", model)
                _store_response_cache_value(cache_key, raw)
                return raw

        logger.error("All models exhausted for llm_text")
        return ""

    async def llm_json_vision(
        self,
        images: list[bytes],
        prompt: str,
        *,
        vision_models: list[str] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        request_timeout: float | None = None,
        max_retries: int | None = None,
        json_schema: dict | None = None,
        schema_name: str = "structured_output",
        strict: bool = True,
    ) -> dict:
        """Send one or more images + a text prompt to a free vision model, return parsed JSON.

        Images should be PNG bytes. They are base64-encoded and sent as data URIs.
        Tries each model in `vision_models` (defaults to VISION_MODELS) in order.
        Returns ``{"_error": ...}`` if all models fail.
        """
        if vision_models:
            models = vision_models
        else:
            candidates = await fetch_free_vision_models(self.api_key, self._http)
            # Probe candidates and use only healthy ones (reuses probe cache).
            vision_client = OpenRouterClient(api_key=self.api_key, models=candidates)
            vision_client._http = self._http  # share the connection pool
            healthy = await vision_client._ensure_healthy()
            models = healthy if healthy else candidates
        content: list[dict] = []
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        schema_body = None
        if json_schema:
            schema_body = {
                "response_format": _build_response_format(
                    json_schema,
                    schema_name=schema_name,
                    strict=strict,
                )
            }
        cache_key = self._cache_key(messages, temperature, schema_body)
        cached = _get_response_cache_value(cache_key)
        if cached is not None:
            logger.info("llm_json_vision cache hit")
            return cached  # type: ignore[return-value]

        last_error = None
        for model in models:
            logger.info("llm_json_vision trying %s (%d image(s))", model, len(images))
            raw = await self._call(
                model,
                messages,
                max_tokens,
                temperature,
                extra_body=schema_body,
                request_timeout=request_timeout,
                max_retries=max_retries,
            )
            if raw is None and schema_body:
                logger.info("Structured vision response unavailable on %s, falling back to prompt-only JSON", model)
                raw = await self._call(
                    model,
                    messages,
                    max_tokens,
                    temperature,
                    request_timeout=request_timeout,
                    max_retries=max_retries,
                )
            if raw is None:
                last_error = f"{model} returned nothing"
                continue
            parsed = _extract_json(raw)
            if parsed is not None:
                if not _looks_like_nonempty_resume_payload(parsed):
                        last_error = f"{model} returned structurally empty resume payload"
                        logger.warning("Empty resume payload from vision model %s", model)
                        continue
                logger.info("llm_json_vision success via %s", model)
                _store_response_cache_value(cache_key, parsed)
                return parsed
            last_error = f"{model} returned non-JSON: {raw[:120]}"
            logger.warning("Non-JSON from vision model %s: %s...", model, raw[:80])

        return {"_error": "vision_llm_failed", "_details": str(last_error)}

    async def close(self):
        await self._http.aclose()
