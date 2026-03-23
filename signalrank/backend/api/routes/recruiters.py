from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.models import Recruiter, User

router = APIRouter(prefix="/api/recruiters", tags=["recruiters"])


class RecruiterFindRequest(BaseModel):
    company: str
    max_results: int = 10


@router.post("/find", status_code=200)
async def find_and_save_recruiters(
    body: RecruiterFindRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.company.strip():
        raise HTTPException(status_code=422, detail="company is required")
    if body.max_results < 1 or body.max_results > 25:
        raise HTTPException(status_code=422, detail="max_results must be 1-25")

    from batch.recruiter_finder import find_recruiters

    found = await find_recruiters(
        company=body.company.strip(),
        max_results=body.max_results,
        db=db,
    )

    inserted = 0
    skipped = 0
    saved = []
    for rec in found:
        stmt = (
            pg_insert(Recruiter)
            .values(
                company=body.company.strip(),
                name=rec["name"],
                email=None,
                linkedin_url=rec["linkedin_url"],
                domain=None,
            )
            .on_conflict_do_nothing(constraint="uq_recruiter_company_linkedin")
        )
        result = await db.execute(stmt)
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
        saved.append({
            "name": rec["name"],
            "linkedin_url": rec["linkedin_url"],
            "confidence": rec["confidence"],
        })

    await db.commit()
    return {"found": len(found), "inserted": inserted, "skipped": skipped, "recruiters": saved}


@router.get("")
async def list_recruiters(
    company: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Recruiter)
    if company:
        q = q.where(Recruiter.company == company)
    result = await db.execute(q.order_by(Recruiter.company, Recruiter.name))
    recs = result.scalars().all()
    return [
        {
            "id": r.id,
            "company": r.company,
            "name": r.name,
            "email": r.email,
            "linkedin_url": r.linkedin_url,
            "domain": r.domain,
        }
        for r in recs
    ]
