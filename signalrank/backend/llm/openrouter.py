import asyncio
import json
import logging
import random

import httpx

logger = logging.getLogger(__name__)

FALLBACK_MODELS = [
    "openrouter/free",
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RETRIES_PER_MODEL = 2


def _extract_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        models: list[str] | None = None,
        timeout: float = 90.0,
    ):
        self.api_key = api_key
        self.models = models or FALLBACK_MODELS
        self._http = httpx.AsyncClient(timeout=timeout)

    async def _call(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str | None:
        for attempt in range(MAX_RETRIES_PER_MODEL + 1):
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
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip() if content else None

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    sleep_time = min(4 ** attempt, 16) + random.uniform(0.5, 2.0)
                    logger.warning(
                        "Rate limited on %s, sleeping %.1fs", model, sleep_time
                    )
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

    async def llm_json(
        self,
        prompt: str | None = None,
        *,
        system: str | None = None,
        user: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict:
        if system and user:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        else:
            messages = [{"role": "user", "content": prompt or ""}]

        last_error = None
        for model in self.models:
            raw = await self._call(model, messages, max_tokens, temperature)
            if raw is None:
                last_error = f"{model} returned nothing"
                continue

            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info("llm_json success via %s", model)
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

        for model in self.models:
            raw = await self._call(model, messages, max_tokens, temperature)
            if raw is not None:
                logger.info("llm_text success via %s", model)
                return raw

        logger.error("All models exhausted for llm_text")
        return ""

    async def close(self):
        await self._http.aclose()
