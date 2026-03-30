from __future__ import annotations

from api.models import Profile

VALID_TEMPLATES = {"classic", "modern", "minimal"}


def get_resume_template(profile: Profile | None, requested: str | None = None) -> str:
    """Resolve resume template: explicit > profile config > default."""
    candidate = requested
    if not candidate and profile and isinstance(getattr(profile, "config_overrides", None), dict):
        resume_cfg = profile.config_overrides.get("resume")
        if isinstance(resume_cfg, dict):
            candidate = resume_cfg.get("template")
    return candidate if candidate and candidate in VALID_TEMPLATES else "classic"


def get_config_overrides(profile: Profile | None) -> dict:
    """Safely get config overrides from profile."""
    return dict(profile.config_overrides or {}) if profile and profile.config_overrides else {}
