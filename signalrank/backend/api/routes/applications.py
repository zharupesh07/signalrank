from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.database import get_db
from api.deps import get_current_user
from api.models import Application, JobRaw, JobResult, Profile, Recruiter, User

router = APIRouter(prefix="/api/applications", tags=["applications"])

VALID_STATUSES = {"interested", "applied", "phone_screen", "interview", "offer", "rejected", "archived"}


VALID_PRIORITIES = {"P1", "P2", "P3"}


class ApplicationCreate(BaseModel):
    job_id: str | None = None
    company: str | None = None
    title: str | None = None
    status: str = "interested"
    notes: str | None = None
    priority: str | None = None
    location_group: str | None = None
    interview_date: str | None = None
    offer_lpa: float | None = None
    system_score: float | None = None
    resume_match_pct: float | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    applied_at: str | None = None
    priority: str | None = None
    location_group: str | None = None
    interview_date: str | None = None
    offer_lpa: float | None = None


class RecruiterPatch(BaseModel):
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    recruiter_linkedin_url: str | None = None


def _serialize_app(a: Application, job_result: JobResult | None = None) -> dict:
    rec = None
    if a.recruiter:
        rec = {
            "id": a.recruiter.id,
            "name": a.recruiter.name,
            "email": a.recruiter.email,
            "linkedin_url": a.recruiter.linkedin_url,
        }
    return {
        "id": a.id,
        "job_id": a.job_id,
        "company": a.company,
        "title": a.title,
        "status": a.status,
        "applied_at": str(a.applied_at) if a.applied_at else None,
        "notes": a.notes,
        "priority": a.priority,
        "location_group": a.location_group,
        "interview_date": str(a.interview_date) if a.interview_date else None,
        "offer_lpa": a.offer_lpa,
        "system_score": a.system_score,
        "resume_match_pct": a.resume_match_pct,
        "job_url": a.job.job_url if a.job else None,
        "company_tier": job_result.company_tier if job_result else None,
        "is_contract": job_result.is_contract if job_result else None,
        "location": a.job.location if a.job else None,
        "recruiter": rec,
    }


@router.get("")
async def list_applications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.recruiter), selectinload(Application.job))
        .where(Application.user_id == current_user.id)
        .order_by(Application.applied_at.desc().nullslast())
    )
    apps = result.scalars().all()

    job_ids = [a.job_id for a in apps if a.job_id]
    jr_map: dict[str, JobResult] = {}
    if job_ids:
        jr_result = await db.execute(
            select(JobResult)
            .where(JobResult.user_id == current_user.id, JobResult.job_id.in_(job_ids))
            .order_by(JobResult.final_score.desc())
        )
        for jr in jr_result.scalars().all():
            if jr.job_id not in jr_map:
                jr_map[jr.job_id] = jr

    return [_serialize_app(a, jr_map.get(a.job_id)) for a in apps]


@router.post("", status_code=201)
async def create_application(
    body: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")
    if body.priority and body.priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"Invalid priority: {body.priority}")
    app = Application(
        user_id=current_user.id,
        job_id=body.job_id,
        company=body.company,
        title=body.title,
        status=body.status,
        notes=body.notes,
        priority=body.priority,
        location_group=body.location_group,
        interview_date=datetime.fromisoformat(body.interview_date) if body.interview_date else None,
        offer_lpa=body.offer_lpa,
        system_score=body.system_score,
        resume_match_pct=body.resume_match_pct,
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
    if body.priority is not None:
        if body.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=422, detail=f"Invalid priority: {body.priority}")
        app.priority = body.priority
    if body.location_group is not None:
        app.location_group = body.location_group
    if body.interview_date is not None:
        app.interview_date = datetime.fromisoformat(body.interview_date)
    if body.offer_lpa is not None:
        app.offer_lpa = body.offer_lpa
    await db.commit()
    return {"status": "updated"}


@router.patch("/{app_id}/recruiter", status_code=200)
async def patch_recruiter(
    app_id: str,
    body: RecruiterPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == current_user.id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    recruiter = None
    if body.recruiter_email and app.company:
        rec_result = await db.execute(
            select(Recruiter).where(Recruiter.company == app.company, Recruiter.email == body.recruiter_email)
        )
        recruiter = rec_result.scalar_one_or_none()

    if not recruiter:
        recruiter = Recruiter(
            company=app.company,
            name=body.recruiter_name,
            email=body.recruiter_email,
            linkedin_url=body.recruiter_linkedin_url,
        )
        db.add(recruiter)
        await db.flush()

    if body.recruiter_name and recruiter.name != body.recruiter_name:
        recruiter.name = body.recruiter_name
    if body.recruiter_linkedin_url and recruiter.linkedin_url != body.recruiter_linkedin_url:
        recruiter.linkedin_url = body.recruiter_linkedin_url

    app.recruiter_id = recruiter.id
    await db.commit()
    return {"recruiter_id": recruiter.id}


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


class ImportFromRunBody(BaseModel):
    run_id: str
    min_score: float = 0.6
    limit: int = 20


@router.post("/import-from-run", status_code=200)
async def import_from_run(
    body: ImportFromRunBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    results = await db.execute(
        select(JobResult, JobRaw)
        .join(JobRaw, JobResult.job_id == JobRaw.id)
        .where(JobResult.run_id == body.run_id, JobResult.user_id == current_user.id)
        .where(JobResult.final_score >= body.min_score)
        .order_by(JobResult.final_score.desc())
        .limit(body.limit)
    )
    rows = results.all()

    existing = await db.execute(
        select(Application.job_id).where(
            Application.user_id == current_user.id, Application.job_id.isnot(None)
        )
    )
    tracked_ids = {r[0] for r in existing.all()}

    created = 0
    skipped = 0
    for job_result, job_raw in rows:
        if job_raw.id in tracked_ids:
            skipped += 1
            continue
        app = Application(
            user_id=current_user.id,
            job_id=job_raw.id,
            company=job_raw.company,
            title=job_raw.title,
            status="interested",
            priority="P2",
            system_score=job_result.final_score,
            resume_match_pct=job_result.semantic_score,
        )
        db.add(app)
        tracked_ids.add(job_raw.id)
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped}


@router.get("/recruiters")
async def list_recruiters_by_company(
    company: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Recruiter)
        .where(Recruiter.company == company, Recruiter.email.isnot(None))
        .order_by(Recruiter.name)
    )
    recs = result.scalars().all()
    return [
        {"id": r.id, "name": r.name, "email": r.email, "linkedin_url": r.linkedin_url}
        for r in recs
    ]


@router.get("/stats")
async def application_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application).where(Application.user_id == current_user.id)
    )
    apps = result.scalars().all()

    by_priority: dict[str, int] = {"P1": 0, "P2": 0, "P3": 0, "unset": 0}
    by_status: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    offers: list[float] = []

    for a in apps:
        key = a.priority if a.priority in VALID_PRIORITIES else "unset"
        by_priority[key] += 1
        if a.status in by_status:
            by_status[a.status] += 1
        if a.offer_lpa is not None:
            offers.append(a.offer_lpa)

    profile_result = await db.execute(
        select(Profile.target_lpa).where(Profile.user_id == current_user.id)
    )
    target_lpa = profile_result.scalar_one_or_none()

    return {
        "total": len(apps),
        "by_priority": by_priority,
        "by_status": by_status,
        "offers_count": len(offers),
        "best_offer_lpa": max(offers) if offers else None,
        "target_lpa": target_lpa,
    }
