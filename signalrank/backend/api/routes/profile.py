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


@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "profile": {
            "resume_text": profile.resume_text if profile else None,
            "distilled_text": profile.distilled_text if profile else None,
            "min_salary": profile.min_salary if profile else None,
            "role_intent": profile.role_intent if profile else None,
            "config_overrides": profile.config_overrides if profile else None,
            "onboarding_complete": profile.onboarding_complete if profile else False,
        } if profile else None,
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
