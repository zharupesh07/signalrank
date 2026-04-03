import json
import os
from typing import Annotated
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_private_url: str = ""
    database_public_url: str = ""
    nextauth_secret: str
    environment: str = "development"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    cors_allow_origin_regex: str = ""
    openrouter_api_key: str = ""
    hunter_api_key: str = ""
    db_pool_size: int = 3
    db_max_overflow: int = 3
    db_pool_timeout: int = 30
    llm_response_cache_max: int = 1000
    resume_preview_cache_max: int = 16
    resume_worker_concurrency: int = 1
    archival_worker_concurrency: int = 1
    run_api_worker: bool = True
    run_resume_worker: bool = True
    run_archival_worker: bool = True
    run_boot_scan: bool = False
    run_boot_embed: bool = False
    database_url_railway: str = ""
    rapidapi_key: str = ""
    scraper_max_results: int = 1500
    scraper_hours_old: int = 24
    scraper_default_country: str = "India"
    scraper_max_terms: int = 1
    linkedin_max_queries: int = 0
    ranker_max_candidates: int = 2000
    ranker_max_description_chars: int = 1200
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                try:
                    loaded = json.loads(text)
                    if isinstance(loaded, list):
                        return [str(o).strip() for o in loaded if str(o).strip()]
                except json.JSONDecodeError:
                    pass
            return [o.strip() for o in text.split(",") if o.strip()]
        return v


settings = Settings()


def _normalize_origin_candidate(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if "://" not in text:
        if text.startswith("localhost:") or text.startswith("127.0.0.1:"):
            text = f"http://{text}"
        elif "." in text and " " not in text and "/" not in text:
            text = f"https://{text}"
        else:
            return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def effective_allowed_origins() -> list[str]:
    origins: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str | None) -> None:
        normalized = _normalize_origin_candidate(candidate)
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        origins.append(normalized)

    for origin in settings.allowed_origins or []:
        _add(origin)

    for env_name in (
        "NEXTAUTH_URL",
        "FRONTEND_URL",
        "APP_URL",
        "PUBLIC_URL",
        "VERCEL_URL",
        "RAILWAY_STATIC_URL",
        "RAILWAY_PUBLIC_DOMAIN",
    ):
        raw = os.getenv(env_name, "")
        if not raw:
            continue
        if raw.strip().startswith("["):
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    for item in loaded:
                        _add(str(item))
                    continue
            except json.JSONDecodeError:
                pass
        for item in raw.split(","):
            _add(item)

    return origins


def effective_allow_origin_regex() -> str | None:
    regex = (settings.cors_allow_origin_regex or "").strip()
    return regex or None


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def runtime_flags(mode: str = "api") -> dict[str, bool]:
    is_worker = mode == "worker"
    return {
        "run_api_worker": _env_truthy("RUN_API_WORKER", is_worker),
        "run_resume_worker": _env_truthy("RUN_RESUME_WORKER", is_worker),
        "run_archival_worker": _env_truthy("RUN_ARCHIVAL_WORKER", is_worker),
        "run_boot_scan": _env_truthy("RUN_BOOT_SCAN", False),
        "run_boot_embed": _env_truthy("RUN_BOOT_EMBED", False),
    }


def api_runtime_flags() -> dict[str, bool]:
    return runtime_flags("api")


def worker_runtime_flags() -> dict[str, bool]:
    return runtime_flags("worker")
