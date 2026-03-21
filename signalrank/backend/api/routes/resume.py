import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import JobRaw, Profile, TailoredResume, User
from llm.openrouter import OpenRouterClient
from llm.resume_tailor import compile_pdf, render_typst, tailor_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["resume"])

VALID_TEMPLATES = {"classic", "modern", "minimal"}


class TailorRequest(BaseModel):
    job_id: str
    template: str = "classic"


@router.post("/tailor")
async def tailor(
    body: TailorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    if body.template not in VALID_TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Template must be one of: {VALID_TEMPLATES}")

    profile_res = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = profile_res.scalar_one_or_none()
    if not profile or not profile.resume_text:
        raise HTTPException(status_code=404, detail="Upload a resume first via /api/onboarding/resume")

    job_res = await db.execute(select(JobRaw).where(JobRaw.id == body.job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing_res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == current_user.id,
            TailoredResume.job_id == body.job_id,
        )
    )
    existing = existing_res.scalar_one_or_none()

    content = await tailor_resume(
        resume_text=profile.resume_text,
        job_title=job.title,
        job_description=job.description or "",
        llm=llm,
    )

    try:
        typst_src = render_typst(content, body.template)
        pdf_bytes = compile_pdf(typst_src)
        pdf_b64 = None
    except Exception as e:
        logger.warning("PDF compile failed: %s", e)
        pdf_bytes = None

    content_dict = {
        "name": content.name, "position": content.position,
        "email": content.email,
        "phone": content.phone, "homepage": content.homepage, "linkedin": content.linkedin, "github": content.github,
        "location": content.location,
        "summary": content.summary,
        "skills": content.skills,
        "experiences": content.experiences,
        "education": content.education,
        "projects": content.projects,
    }

    if existing:
        existing.content_json = content_dict
        existing.template = body.template
        existing.pdf_path = None
    else:
        db.add(
            TailoredResume(
                user_id=current_user.id,
                job_id=body.job_id,
                content_json=content_dict,
                template=body.template,
            )
        )
    await db.commit()

    return {
        "status": "ok",
        "job_id": body.job_id,
        "template": body.template,
        "content": content_dict,
        "pdf_available": pdf_bytes is not None,
    }


@router.get("/tailor/{job_id}")
async def download_tailored(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == current_user.id,
            TailoredResume.job_id == job_id,
        )
    )
    tailored = res.scalar_one_or_none()
    if not tailored:
        raise HTTPException(status_code=404, detail="No tailored resume for this job")

    from llm.resume_tailor import TailoredContent, compile_pdf, render_typst

    content = TailoredContent(**tailored.content_json)
    typst_src = render_typst(content, tailored.template or "classic")
    pdf_bytes = compile_pdf(typst_src)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume_{job_id[:8]}.pdf"'},
    )


@router.get("/templates")
async def list_templates():
    return {"templates": sorted(VALID_TEMPLATES)}
