import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import JobRaw, Profile, TailoredResume, User
from llm.openrouter import OpenRouterClient
from llm.email_generator import generate_email
from llm.resume_tailor import TailoredContent, compile_pdf, render_typst, tailor_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["resume"])

VALID_TEMPLATES = {"classic", "modern", "minimal"}


class TailorRequest(BaseModel):
    job_id: str
    template: str = "classic"


class EmailRequest(BaseModel):
    job_id: str
    recruiter_name: str = "Hiring Manager"


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
    template: str = Query("classic"),
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
        return JSONResponse(status_code=202, content={"status": "pending", "job_id": str(job_id)})

    content = TailoredContent(**tailored.content_json)
    typst_src = render_typst(content, template)
    pdf_bytes = compile_pdf(typst_src)

    company = ""
    job_res = await db.execute(select(JobRaw).where(JobRaw.id == job_id))
    job = job_res.scalar_one_or_none()
    if job and job.company:
        company = "_" + job.company.replace(" ", "_").replace("/", "_")[:30]

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume{company}_{job_id[:8]}.pdf"'},
    )


@router.post("/email")
async def generate_cold_email(
    body: EmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    job_res = await db.execute(select(JobRaw).where(JobRaw.id == body.job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    tailored_res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == current_user.id,
            TailoredResume.job_id == body.job_id,
        )
    )
    tailored = tailored_res.scalar_one_or_none()

    bullets: list[str] = []
    if tailored and tailored.content_json:
        for exp in tailored.content_json.get("experiences", [])[:2]:
            bullets.extend(exp.get("bullets", [])[:3])
    if not bullets:
        profile_res = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
        profile = profile_res.scalar_one_or_none()
        if profile and profile.resume_text:
            bullets = [line.strip("- ") for line in profile.resume_text.split("\n") if line.strip().startswith("-")][:5]

    email = await generate_email(
        jd=job.description or "",
        company=job.company or "",
        role=job.title or "",
        recruiter_name=body.recruiter_name,
        tailored_bullets=bullets,
        job_url=job.job_url if hasattr(job, "job_url") else None,
        llm=llm,
    )

    return {"subject": email.subject, "body": email.body}


@router.get("/templates")
async def list_templates():
    return {"templates": sorted(VALID_TEMPLATES)}
