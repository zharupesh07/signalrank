from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Profile, User
from batch.context import load_base_config
from domain.profile_rules import enrich_config_with_profile_rules
from domain.resume_editor import merge_resume_editor, parse_resume_editor, serialize_resume_editor
from domain.role_taxonomy import CANONICAL_ROLE_OPTIONS, LOCATION_OPTIONS, ROLE_UI_OPTIONS, TIER_OPTIONS

router = APIRouter(prefix="/api", tags=["profile"])


def _deep_merge_dict(base: dict | None, incoming: dict | None) -> dict | None:
    if base is None:
        return incoming
    if incoming is None:
        return base
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged.get(key), value)
        else:
            merged[key] = value
    return merged


def _profile_resume_template(profile: Profile | None) -> str | None:
    if not profile or not isinstance(profile.config_overrides, dict):
        return None
    resume_cfg = profile.config_overrides.get("resume")
    if not isinstance(resume_cfg, dict):
        return None
    template = resume_cfg.get("template")
    return template if isinstance(template, str) else None


def _profile_resume_editor(profile: Profile | None) -> dict:
    derived = parse_resume_editor(profile.resume_text if profile else None)
    if profile and isinstance(profile.config_overrides, dict):
        editor = profile.config_overrides.get("resume_editor")
        if isinstance(editor, dict):
            return merge_resume_editor(editor, derived)
    return derived


def _drop_stored_resume_editor(profile: Profile) -> None:
    if not isinstance(profile.config_overrides, dict):
        return
    overrides = dict(profile.config_overrides)
    if "resume_editor" in overrides:
        overrides.pop("resume_editor", None)
        profile.config_overrides = overrides or None


def _looks_like_public_url(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith(("http://", "https://", "www."))
        or ("." in stripped and " " not in stripped)
    )


def _trim_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = value.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            cleaned.append(item)
    return cleaned


class ResumeExperienceInput(BaseModel):
    title: str = ""
    company: str = ""
    dates: str = ""
    location: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("title", "company", "dates", "location", mode="before")
    @classmethod
    def _trim_str(cls, value):
        return str(value or "").strip()

    @field_validator("bullets", mode="before")
    @classmethod
    def _normalize_bullets(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.splitlines()
        return _trim_list([str(item or "").lstrip("-*• ").strip() for item in value])

    @model_validator(mode="after")
    def _validate_shape(self):
        has_content = bool(self.title or self.company or self.dates or self.location or self.bullets)
        if has_content and not self.title:
            raise ValueError("Experience title is required")
        if has_content and not self.company:
            raise ValueError("Experience company is required")
        return self


class ResumeProjectInput(BaseModel):
    name: str = ""
    url: str = ""
    description: str = ""

    @field_validator("name", "url", "description", mode="before")
    @classmethod
    def _trim_str(cls, value):
        return str(value or "").strip()

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str):
        if value and not _looks_like_public_url(value):
            raise ValueError("Project URL must look like a public URL")
        return value

    @model_validator(mode="after")
    def _validate_shape(self):
        has_content = bool(self.name or self.url or self.description)
        if has_content and not self.name:
            raise ValueError("Project name is required")
        return self


class ResumeSkillGroupInput(BaseModel):
    category: str = ""
    items: list[str] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def _trim_category(cls, value):
        return str(value or "").strip()

    @field_validator("items", mode="before")
    @classmethod
    def _normalize_items(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        return _trim_list([str(item or "").strip() for item in value])

    @model_validator(mode="after")
    def _validate_shape(self):
        if self.category and not self.items:
            raise ValueError("Skill group items are required")
        if self.items and not self.category:
            raise ValueError("Skill category is required")
        return self


class ResumeEditorInput(BaseModel):
    name: str = ""
    position: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    summary: str = ""
    experiences: list[ResumeExperienceInput] = Field(default_factory=list)
    projects: list[ResumeProjectInput] = Field(default_factory=list)
    skills: list[ResumeSkillGroupInput] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    @field_validator("name", "position", "phone", "location", "linkedin", "github", "website", "summary", mode="before")
    @classmethod
    def _trim_text(cls, value):
        return str(value or "").strip()

    @field_validator("email", mode="before")
    @classmethod
    def _trim_email(cls, value):
        return str(value or "").strip()

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str):
        if value and ("@" not in value or "." not in value.split("@")[-1]):
            raise ValueError("Email must be valid")
        return value

    @field_validator("linkedin", "github", "website")
    @classmethod
    def _validate_public_links(cls, value: str, info):
        if value and not _looks_like_public_url(value):
            raise ValueError(f"{info.field_name.capitalize()} must look like a public URL")
        return value

    @field_validator("certifications", mode="before")
    @classmethod
    def _normalize_certifications(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.splitlines()
        return _trim_list([str(item or "").lstrip("-*• ").strip() for item in value])

    @field_validator("experiences", "projects", "skills", mode="after")
    @classmethod
    def _drop_empty_rows(cls, value):
        rows: list = []
        for item in value:
            dumped = item.model_dump()
            if any(
                dumped.get(key)
                for key in dumped
            ):
                rows.append(item)
        return rows


class ProfileUpdate(BaseModel):
    resume_text: str | None = None
    distilled_text: str | None = None
    min_salary: int | None = None
    min_yoe: int | None = None
    max_yoe: int | None = None
    role_intent: str | None = None
    config_overrides: dict | None = None
    onboarding_complete: bool | None = None
    target_lpa: float | None = None
    custom_search_queries: list[str] | None = None
    target_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    scraper_hours_old: int | None = None
    scraper_max_terms: int | None = None
    resume_editor: ResumeEditorInput | None = None


@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    p = result.scalar_one_or_none()
    profile_data = {
        "resume_text": p.resume_text if p else None,
        "resume_editor": _profile_resume_editor(p),
        "distilled_text": p.distilled_text if p else None,
        "min_salary": p.min_salary if p else None,
        "role_intent": p.role_intent if p else None,
        "min_yoe": p.min_yoe if p else None,
        "max_yoe": p.max_yoe if p else None,
        "target_lpa": p.target_lpa if p else None,
        "target_roles": p.target_roles if p else None,
        "preferred_locations": p.preferred_locations if p else None,
        "custom_search_queries": p.custom_search_queries if p else None,
        "config_overrides": p.config_overrides if p else None,
        "resume_template": _profile_resume_template(p),
        "scraper_hours_old": p.scraper_hours_old if p else None,
        "scraper_max_terms": p.scraper_max_terms if p else None,
        "onboarding_complete": p.onboarding_complete if p else False,
        "skills": p.skills if p and p.skills else [],
    }
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "is_admin": current_user.is_admin,
        "profile": profile_data,
        **profile_data,
    }


@router.get("/profile/options")
async def get_profile_options(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    cfg = enrich_config_with_profile_rules(
        load_base_config(),
        resume_text=profile.resume_text if profile else "",
        profile_roles=profile.target_roles if profile else [],
    )
    company_scoring = cfg.get("company_scoring", {}) or {}
    ranking = cfg.get("ranking", {}) or {}
    return {
        "role_options": ROLE_UI_OPTIONS,
        "canonical_role_options": CANONICAL_ROLE_OPTIONS,
        "location_options": LOCATION_OPTIONS,
        "tier_options": TIER_OPTIONS,
        "title_penalty_rules": ranking.get("profile_title_rules", {"strong": [], "adjacent": [], "hybrid": []}),
        "company_tier_lists": {
            "tier_ss": company_scoring.get("tier_ss", []) or [],
            "tier_s": company_scoring.get("tier_s", []) or [],
        },
    }


@router.patch("/profile", status_code=200)
async def update_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.id).with_for_update()
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.add(profile)
        await db.flush()

    for field, value in body.model_dump(exclude_none=True).items():
        if field == "config_overrides":
            profile.config_overrides = _deep_merge_dict(profile.config_overrides, value)
            continue
        if field == "resume_editor":
            editor_payload = value
            profile.config_overrides = _deep_merge_dict(profile.config_overrides, {"resume_editor": editor_payload})
            profile.resume_text = serialize_resume_editor(editor_payload)
            profile.resume_embedding = None
            continue
        if field in {"resume_text", "distilled_text"}:
            profile.resume_embedding = None
        if field == "resume_text":
            _drop_stored_resume_editor(profile)
        setattr(profile, field, value)

    await db.commit()
    return {"status": "updated"}
