import json
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
    db_pool_size: int = 2
    db_max_overflow: int = 1
    db_pool_timeout: int = 30
    resume_worker_concurrency: int = 1
    archival_worker_concurrency: int = 1
    run_api_worker: bool = True
    run_resume_worker: bool = True
    run_archival_worker: bool = True
    run_boot_scan: bool = False
    run_boot_embed: bool = False

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
