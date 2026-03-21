from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Application, User

router = APIRouter(prefix="/api/applications", tags=["applications"])

VALID_STATUSES = {"interested", "applied", "phone_screen", "interview", "offer", "rejected", "archived"}


class ApplicationCreate(BaseModel):
    job_id: str | None = None
    company: str | None = None
    title: str | None = None
    status: str = "interested"
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    applied_at: str | None = None


@router.get("")
async def list_applications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application)
        .where(Application.user_id == current_user.id)
        .order_by(Application.applied_at.desc().nullslast())
    )
    apps = result.scalars().all()
    return [
        {
            "id": a.id,
            "job_id": a.job_id,
            "company": a.company,
            "title": a.title,
            "status": a.status,
            "applied_at": str(a.applied_at) if a.applied_at else None,
            "notes": a.notes,
        }
        for a in apps
    ]


@router.post("", status_code=201)
async def create_application(
    body: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")
    app = Application(
        user_id=current_user.id,
        job_id=body.job_id,
        company=body.company,
        title=body.title,
        status=body.status,
        notes=body.notes,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return {"id": app.id, "status": app.status}


@router.patch("/{app_id}", status_code=200)
async def update_application(
    app_id: str,
    body: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == current_user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if body.status:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")
        app.status = body.status
        if body.status == "applied" and not app.applied_at:
            app.applied_at = datetime.now(timezone.utc)
    if body.notes is not None:
        app.notes = body.notes
    await db.commit()
    return {"status": "updated"}


@router.delete("/{app_id}", status_code=204)
async def delete_application(
    app_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == current_user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    await db.delete(app)
    await db.commit()
