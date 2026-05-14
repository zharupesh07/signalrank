import json
import os
import secrets
from typing import Annotated
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _desktop_data_dir(configured: str = ""):
    from pathlib import Path
    import sys

    if configured:
        root = Path(configured).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "SignalRank"
    elif sys.platform.startswith("win"):
        root = Path(os.getenv("APPDATA", str(Path.home()))) / "SignalRank"
    else:
        root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "signalrank"
    root.mkdir(parents=True, exist_ok=True)
    return root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    signalrank_mode: str = "server"
    signalrank_app_data_dir: str = ""
    database_url: str = ""
    database_private_url: str = ""
    database_public_url: str = ""
    nextauth_secret: str = ""
    environment: str = "development"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    cors_allow_origin_regex: str = ""
    llm_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    hunter_api_key: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    llm_response_cache_max: int = 1000
    llm_semaphore: int = 3
    resume_preview_cache_max: int = 16
    stats_cache_ttl_seconds: int = 30
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
    linkedin_cookie_header: str = ""
    ranker_max_candidates: int = 10000
    ranker_max_description_chars: int = 1200
    job_availability_archive_after_run: bool = True
    job_availability_archive_limit: int = 100
    max_active_runs_per_user: int = 1
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    @field_validator("database_url", mode="before")
    @classmethod
    def default_database_url(cls, v):
        if v:
            return v
        if os.getenv("SIGNALRANK_MODE", "").strip().lower() == "desktop":
            return f"sqlite+aiosqlite:///{_desktop_data_dir(os.getenv('SIGNALRANK_APP_DATA_DIR', '')) / 'signalrank.db'}"
        return "postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank"

    @field_validator("nextauth_secret", mode="before")
    @classmethod
    def default_nextauth_secret(cls, v):
        if v:
            return v
        if os.getenv("SIGNALRANK_MODE", "").strip().lower() == "desktop":
            return secrets.token_urlsafe(32)
        return ""

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


def is_desktop_mode() -> bool:
    return settings.signalrank_mode.strip().lower() == "desktop"


def desktop_data_dir():
    return _desktop_data_dir(settings.signalrank_app_data_dir)


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
    if regex:
        return regex
    if is_desktop_mode():
        return r"^http://(localhost|127\.0\.0\.1):\d+$"
    return None


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def runtime_flags(mode: str = "api") -> dict[str, bool]:
    is_worker = mode == "worker"
    desktop = is_desktop_mode()
    return {
        "run_api_worker": _env_truthy("RUN_API_WORKER", True if desktop else is_worker),
        "run_resume_worker": _env_truthy("RUN_RESUME_WORKER", True if desktop else is_worker),
        "run_archival_worker": _env_truthy("RUN_ARCHIVAL_WORKER", False if desktop else is_worker),
        "run_boot_scan": _env_truthy("RUN_BOOT_SCAN", False),
        "run_boot_embed": _env_truthy("RUN_BOOT_EMBED", False),
    }


def api_runtime_flags() -> dict[str, bool]:
    return runtime_flags("api")


def worker_runtime_flags() -> dict[str, bool]:
    return runtime_flags("worker")
