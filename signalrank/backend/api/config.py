import json
import os
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    nextauth_secret: str
    environment: str = "development"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    openrouter_api_key: str = ""
    hunter_api_key: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
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
