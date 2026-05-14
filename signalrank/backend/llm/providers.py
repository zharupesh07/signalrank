import base64
import logging
from typing import Literal

import httpx

from api.config import settings
from llm.openrouter import (
    OpenRouterClient,
    _build_response_format,
    _extract_json,
    _extract_response_content,
    _llm_semaphore,
)

logger = logging.getLogger(__name__)

ProviderName = Literal["openrouter", "openai", "anthropic"]

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

OPENAI_DEFAULT_MODELS = ["gpt-4.1-mini", "gpt-4.1"]
ANTHROPIC_DEFAULT_MODELS = ["claude-sonnet-4-20250514", "claude-opus-4-1-20250805"]


def normalize_provider(provider: str | None) -> ProviderName:
    value = (provider or "").strip().lower()
    if value in {"openai", "anthropic"}:
        return value  # type: ignore[return-value]
    return "openrouter"


def provider_display_name(provider: str) -> str:
    return {
        "openrouter": "OpenRouter",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
    }.get(provider, provider)


def default_models_for_provider(provider: ProviderName) -> list[str]:
    if provider == "openai":
        return OPENAI_DEFAULT_MODELS
    if provider == "anthropic":
        return ANTHROPIC_DEFAULT_MODELS
    return []


def configured_api_key(provider: ProviderName) -> str:
    if provider == "openai":
        return settings.openai_api_key
    if provider == "anthropic":
        return settings.anthropic_api_key
    return settings.openrouter_api_key


class DirectProviderClient:
    def __init__(
        self,
        *,
        provider: ProviderName,
        api_key: str,
        models: list[str] | None = None,
        timeout: float = 90.0,
    ):
        self.provider = provider
        self.api_key = api_key
        self.models = models or default_models_for_provider(provider)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def probe_models(self, *, limit: int | None = None) -> list[str]:
        healthy: list[str] = []
        for model in self.models[:limit] if limit else self.models:
            raw = await self._call(
                model,
                [{"role": "user", "content": "Say hi"}],
                max_tokens=5,
                temperature=0.0,
                request_timeout=10.0,
            )
            if raw:
                healthy.append(model)
        if not healthy:
            logger.warning("%s provider probe failed for all models", self.provider)
        return healthy

    async def validate_api_key(self) -> bool:
        return bool(await self.probe_models(limit=1))

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
        del max_retries
        async with _llm_semaphore:
            if self.provider == "openai":
                return await self._call_openai(
                    model,
                    messages,
                    max_tokens,
                    temperature,
                    extra_body=extra_body,
                    request_timeout=request_timeout,
                )
            return await self._call_anthropic(
                model,
                messages,
                max_tokens,
                temperature,
                request_timeout=request_timeout,
            )

    async def _call_openai(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        *,
        extra_body: dict | None,
        request_timeout: float | None,
    ) -> str | None:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if extra_body:
            payload.update(extra_body)
        try:
            response = await self._http.post(
                OPENAI_CHAT_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=request_timeout,
            )
            response.raise_for_status()
            return (_extract_response_content(response.json()) or "").strip() or None
        except Exception as exc:
            logger.warning("OpenAI call failed for %s: %s", model, exc)
            return None

    async def _call_anthropic(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        *,
        request_timeout: float | None,
    ) -> str | None:
        system = ""
        anthropic_messages: list[dict] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                system = str(message.get("content") or "")
                continue
            if role in {"user", "assistant"}:
                anthropic_messages.append(
                    {"role": role, "content": message.get("content") or ""}
                )
        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        try:
            response = await self._http.post(
                ANTHROPIC_MESSAGES_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=request_timeout,
            )
            response.raise_for_status()
            return (_extract_response_content(response.json()) or "").strip() or None
        except Exception as exc:
            logger.warning("Anthropic call failed for %s: %s", model, exc)
            return None

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

        extra_body = None
        if json_schema and self.provider == "openai":
            extra_body = {
                "response_format": _build_response_format(
                    json_schema,
                    schema_name=schema_name,
                    strict=strict,
                )
            }
        if json_schema and self.provider == "anthropic":
            messages[-1]["content"] = (
                f"{messages[-1]['content']}\n\nReturn only JSON that matches this schema:\n"
                f"{json_schema}"
            )

        last_error = None
        for model in self.models:
            raw = await self._call(
                model,
                messages,
                max_tokens,
                temperature,
                extra_body=extra_body,
            )
            if not raw:
                last_error = f"{model} returned nothing"
                continue
            parsed = _extract_json(raw)
            if parsed is not None:
                logger.info("llm_json success via %s/%s", self.provider, model)
                return parsed
            last_error = f"{model} returned non-JSON: {raw[:100]}"
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
            if raw:
                logger.info("llm_text success via %s/%s", self.provider, model)
                return raw
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
        del max_retries, schema_name, strict
        models = vision_models or self.models
        messages = [{"role": "user", "content": self._vision_content(images, prompt)}]
        if json_schema:
            messages[0]["content"].append(
                {
                    "type": "text",
                    "text": f"Return only JSON that matches this schema: {json_schema}",
                }
            )
        last_error = None
        for model in models:
            raw = await self._call(
                model,
                messages,
                max_tokens,
                temperature,
                request_timeout=request_timeout,
            )
            if not raw:
                last_error = f"{model} returned nothing"
                continue
            parsed = _extract_json(raw)
            if parsed is not None:
                return parsed
            last_error = f"{model} returned non-JSON: {raw[:100]}"
        return {"_error": "vision_llm_failed", "_details": str(last_error)}

    def _vision_content(self, images: list[bytes], prompt: str) -> list[dict]:
        content: list[dict] = []
        for image in images:
            encoded = base64.b64encode(image).decode()
            if self.provider == "anthropic":
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": encoded,
                        },
                    }
                )
            else:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )
        content.append({"type": "text", "text": prompt})
        return content

    async def close(self):
        await self._http.aclose()


def build_llm_client(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    timeout: float = 90.0,
):
    selected = normalize_provider(provider or settings.llm_provider)
    key = api_key or configured_api_key(selected)
    if selected == "openrouter":
        return OpenRouterClient(api_key=key, timeout=timeout)
    return DirectProviderClient(provider=selected, api_key=key, timeout=timeout)
