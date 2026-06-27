"""JobDigest configuration.

Non-secret settings come from ``jobdigest.yaml`` (committed); secrets come from
the environment (GitHub Secrets at runtime), never from the YAML. This keeps the
customization surface — resumes, recipients, filters — in one reviewable file,
while credentials stay out of the repo entirely.

Nothing here has behavior yet; later phases import `load_config()` to drive the
ingest -> score -> digest pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, EmailStr, Field

CONFIG_PATH = Path(__file__).with_name("jobdigest.yaml")


class Profile(BaseModel):
    id: str
    resume: str
    titles: list[str]


class Seniority(BaseModel):
    sweet_spot: tuple[int, int] = (3, 6)
    hard_exclude_min_years: int = 10


class Filters(BaseModel):
    exclude_work_auth: list[str] = Field(
        default_factory=lambda: ["citizen_required", "clearance_required", "itar_us_person"]
    )
    seniority: Seniority = Field(default_factory=Seniority)


class Search(BaseModel):
    country: str = "USA"
    sites: list[str] = Field(default_factory=lambda: ["linkedin", "google"])
    remote: bool = True
    hours_old: int = 24


class Scoring(BaseModel):
    shortlist_per_profile: int = 28
    provider: str = "openrouter"
    model_cheap: str = "anthropic/claude-3.5-haiku"
    model_strong: str = "anthropic/claude-sonnet-4"


class Digest(BaseModel):
    group_by: Literal["domain", "profile"] = "domain"
    routing: Literal["combined", "per_profile"] = "combined"
    top_n: int = 12
    send_hour_local: int = 6
    timezone: str = "America/Los_Angeles"


class Secrets(BaseModel):
    """Resolved from env at runtime. Empty here = not yet provided."""

    database_url: str = ""
    openrouter_api_key: str = ""
    gmail_user: str = ""
    gmail_app_password: str = ""

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            gmail_user=os.getenv("GMAIL_USER", ""),
            gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", ""),
        )

    def missing(self) -> list[str]:
        return [k for k, v in self.model_dump().items() if not v]


class JobDigestConfig(BaseModel):
    profiles: list[Profile]
    recipients: list[EmailStr]
    search: Search = Field(default_factory=Search)
    filters: Filters = Field(default_factory=Filters)
    scoring: Scoring = Field(default_factory=Scoring)
    digest: Digest = Field(default_factory=Digest)
    secrets: Secrets = Field(default_factory=Secrets)


def load_config(path: Path | str = CONFIG_PATH) -> JobDigestConfig:
    """Load + validate jobdigest.yaml and overlay env-sourced secrets."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    cfg = JobDigestConfig(**data)
    cfg.secrets = Secrets.from_env()
    return cfg


if __name__ == "__main__":
    # Quick self-check: `python -m jobdigest.config`
    c = load_config()
    print(f"profiles: {[p.id for p in c.profiles]}")
    print(f"recipients: {list(c.recipients)}")
    print(f"sites: {c.search.sites}  country: {c.search.country}  hours_old: {c.search.hours_old}")
    print(f"exclude_work_auth: {c.filters.exclude_work_auth}")
    print(f"digest: group_by={c.digest.group_by} routing={c.digest.routing} top_n={c.digest.top_n} "
          f"{c.digest.send_hour_local}:00 {c.digest.timezone}")
    miss = c.secrets.missing()
    print(f"secrets present: {not miss}" + (f" (missing: {miss})" if miss else ""))