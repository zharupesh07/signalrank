from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Profile, User

router = APIRouter(prefix="/api", tags=["profile"])


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


@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    p = result.scalar_one_or_none()
    profile_data = {
        "resume_text": p.resume_text if p else None,
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
        "scraper_hours_old": p.scraper_hours_old if p else None,
        "scraper_max_terms": p.scraper_max_terms if p else None,
        "onboarding_complete": p.onboarding_complete if p else False,
        "skills": [],
    }
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "profile": profile_data,
        **profile_data,
    }


@router.patch("/profile", status_code=200)
async def update_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.add(profile)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    await db.commit()
    return {"status": "updated"}
