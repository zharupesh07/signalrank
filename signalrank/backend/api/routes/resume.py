import logging
import json
import hashlib
import time
from dataclasses import asdict
from collections import OrderedDict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.config import settings
from api.deps import get_current_user, get_user_profile
from api.deps_llm import get_llm_client
from api.helpers import VALID_TEMPLATES, get_resume_template
from api.models import JobRaw, Profile, TailoredResume, User
from api.routes.profile import ResumeEditorInput
from domain.resume_editor import editor_to_tailored_content, merge_resume_editor, parse_resume_editor
from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["resume"])

_preview_cache: OrderedDict[str, tuple[float, str, bytes, object]] = OrderedDict()
_PREVIEW_CACHE_MAX = settings.resume_preview_cache_max
_PREVIEW_CACHE_TTL = 900


def _stored_resume_editor(profile: Profile | None) -> dict | None:
    if not profile or not isinstance(profile.config_overrides, dict):
        return None
    editor = profile.config_overrides.get("resume_editor")
    return editor if isinstance(editor, dict) else None


def _preview_cache_key(template: str, editor_payload: dict) -> str:
    blob = json.dumps({"template": template, "editor": editor_payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(blob.encode()).hexdigest()


def _get_preview_cache(cache_key: str):
    cached = _preview_cache.get(cache_key)
    if not cached:
        return None
    if (time.monotonic() - cached[0]) >= _PREVIEW_CACHE_TTL:
        _preview_cache.pop(cache_key, None)
        return None
    _preview_cache.move_to_end(cache_key)
    return cached[1:]


def _store_preview_cache(cache_key: str, typst_src: str, pdf_bytes: bytes, validation: object) -> None:
    if _PREVIEW_CACHE_MAX <= 0:
        return
    _preview_cache[cache_key] = (time.monotonic(), typst_src, pdf_bytes, validation)
    _preview_cache.move_to_end(cache_key)
    while len(_preview_cache) > _PREVIEW_CACHE_MAX:
        _preview_cache.popitem(last=False)


class TailorRequest(BaseModel):
    job_id: str
    template: str | None = None


class EmailRequest(BaseModel):
    job_id: str
    recruiter_name: str = "Hiring Manager"


class PreviewRequest(BaseModel):
    template: str | None = None
    resume_editor: ResumeEditorInput | None = None
    debug: bool = False



@router.post("/tailor")
async def tailor(
    body: TailorRequest,
    profile: Profile | None = Depends(get_user_profile),
    db: AsyncSession = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    from llm.resume_tailor import render_compile_validate_content, tailor_resume

    if body.template is not None and body.template not in VALID_TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Template must be one of: {VALID_TEMPLATES}")

    if not profile or not profile.resume_text:
        raise HTTPException(status_code=404, detail="Upload a resume first via /api/onboarding/resume")
    selected_template = get_resume_template(profile, body.template)

    job_res = await db.execute(select(JobRaw).where(JobRaw.id == body.job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.title or not job.description:
        raise HTTPException(status_code=422, detail="Job is missing title or description")

    existing_res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == profile.user_id,
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
        _, pdf_bytes, validation = render_compile_validate_content(content, selected_template)
    except Exception as e:
        logger.warning("PDF compile failed: %s", e)
        pdf_bytes = None
        validation = None

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
        existing.template = selected_template
        existing.pdf_path = None
    else:
        db.add(
            TailoredResume(
                user_id=profile.user_id,
                job_id=body.job_id,
                content_json=content_dict,
                template=selected_template,
            )
        )
    await db.commit()

    return {
        "status": "ok",
        "job_id": body.job_id,
        "template": selected_template,
        "content": content_dict,
        "pdf_available": pdf_bytes is not None,
        "validation": validation.__dict__ if validation else None,
    }


@router.get("/tailor/{job_id}")
async def download_tailored(
    job_id: str,
    template: str | None = Query(None),
    profile: Profile | None = Depends(get_user_profile),
    db: AsyncSession = Depends(get_db),
):
    from llm.resume_tailor import TailoredContent, render_and_compile_content

    res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == (profile.user_id if profile else None),
            TailoredResume.job_id == job_id,
        )
    )
    tailored = res.scalar_one_or_none()
    if not tailored:
        return JSONResponse(status_code=202, content={"status": "pending", "job_id": str(job_id)})
    selected_template = get_resume_template(profile, template) if (template or profile) else (tailored.template or "classic")

    content = None
    if tailored.pdf_bytes and selected_template == (tailored.template or "classic"):
        pdf_bytes = tailored.pdf_bytes
    else:
        if not tailored.content_json:
            return JSONResponse(status_code=202, content={"status": "pending", "job_id": str(job_id)})
        content = TailoredContent(**tailored.content_json)
        _, pdf_bytes = render_and_compile_content(content, selected_template)

    job_res = await db.execute(select(JobRaw).where(JobRaw.id == job_id))
    job = job_res.scalar_one_or_none()

    candidate = ((content.name if content else None) or "candidate").lower().replace(" ", "_")
    company_part = (job.company or "").lower().replace(" ", "_").replace("/", "_")[:20] if job else ""
    title_part = (job.title or "").lower().replace(" ", "_").replace("/", "_")[:20] if job else ""
    parts = [p for p in [candidate, company_part, title_part] if p]
    filename = "_".join(parts) + ".pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/email")
async def generate_cold_email(
    body: EmailRequest,
    profile: Profile | None = Depends(get_user_profile),
    db: AsyncSession = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    from llm.email_generator import generate_email

    job_res = await db.execute(select(JobRaw).where(JobRaw.id == body.job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    tailored_res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == (profile.user_id if profile else None),
            TailoredResume.job_id == body.job_id,
        )
    )
    tailored = tailored_res.scalar_one_or_none()

    if tailored and tailored.email_body:
        return {"subject": tailored.email_subject, "body": tailored.email_body}

    bullets: list[str] = []
    if tailored and tailored.content_json:
        for exp in tailored.content_json.get("experiences", [])[:2]:
            bullets.extend(exp.get("bullets", [])[:3])
    if not bullets and profile and profile.resume_text:
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


@router.post("/preview")
async def preview_resume(
    body: PreviewRequest,
    profile: Profile | None = Depends(get_user_profile),
    db: AsyncSession = Depends(get_db),
):
    from llm.resume_tailor import render_compile_validate_content

    if body.template is not None and body.template not in VALID_TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Template must be one of: {VALID_TEMPLATES}")

    if not profile and body.resume_editor is None:
        raise HTTPException(status_code=404, detail="Upload a resume first via /api/onboarding/resume")

    editor_payload = (
        body.resume_editor.model_dump()
        if body.resume_editor
        else merge_resume_editor(_stored_resume_editor(profile), parse_resume_editor(profile.resume_text if profile else None))
    )
    if not any(editor_payload.get(field) for field in ("name", "summary", "experiences", "projects", "skills", "certifications")):
        raise HTTPException(status_code=404, detail="Upload a resume first via /api/onboarding/resume")

    selected_template = get_resume_template(profile, body.template)
    content = editor_to_tailored_content(editor_payload)
    cache_key = _preview_cache_key(selected_template, editor_payload)
    cached = _get_preview_cache(cache_key)
    if cached is not None:
        typst_src, pdf_bytes, validation = cached
        logger.info("Resume preview cache hit for template=%s", selected_template)
    else:
        typst_src, pdf_bytes, validation = render_compile_validate_content(content, selected_template)
        _store_preview_cache(cache_key, typst_src, pdf_bytes, validation)

    if body.debug:
        return JSONResponse(
            {
                "content": {
                    "name": content.name,
                    "position": content.position,
                    "email": content.email,
                    "phone": content.phone,
                    "homepage": content.homepage,
                    "linkedin": content.linkedin,
                    "github": content.github,
                    "location": content.location,
                    "summary": content.summary,
                    "skills": content.skills,
                    "experiences": content.experiences,
                    "education": content.education,
                    "projects": content.projects,
                    "certifications": content.certifications,
                    "par_leading": content.par_leading,
                    "list_spacing": content.list_spacing,
                },
                "template": selected_template,
                "validation": asdict(validation),
                "typst_source": typst_src,
                "pdf_size": len(pdf_bytes),
            }
        )

    filename_root = (content.name or "resume_preview").lower().replace(" ", "_")
    validation_header = quote(json.dumps(asdict(validation), separators=(",", ":")))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename_root}.pdf"',
            "Access-Control-Expose-Headers": "X-Resume-Validation",
            "X-Resume-Validation": validation_header,
        },
    )


@router.post("/regenerate-all")
async def regenerate_all_resumes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from batch.resume_worker import force_regenerate_all

    count = await force_regenerate_all(db, current_user.id)
    return {"enqueued": count}


@router.get("/templates")
async def list_templates():
    return {"templates": sorted(VALID_TEMPLATES)}
