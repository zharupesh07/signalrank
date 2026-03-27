import asyncio
import io
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Profile, User
from llm.onboarding import generate_onboarding_questions
from llm.openrouter import OpenRouterClient
from llm.resume_parser import ResumeParseResult, parse_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _extract_text_from_pdf(content: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        logger.warning("PDF extraction failed: %s", e)
        return ""


def _extract_text_from_docx(content: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        logger.warning("DOCX extraction failed: %s", e)
        return ""


async def _parse_and_update_profile(user_id: str, resume_text: str, llm: OpenRouterClient) -> None:
    """Background task: parse resume with LLM and update profile fields."""
    try:
        parsed = await parse_resume(resume_text, llm)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile:
                return
            profile.skills = parsed.skills
            parts = []
            if parsed.recent_titles:
                parts.append("Recent roles: " + ", ".join(parsed.recent_titles))
            if parsed.skills:
                parts.append("Skills: " + ", ".join(parsed.skills))
            if parsed.years_of_experience:
                parts.append(f"Experience: {parsed.years_of_experience} years")
            if parts:
                profile.distilled_text = "\n".join(parts)
            await db.commit()
            logger.info("Background parse complete for user=%s (%d skills)", user_id, len(parsed.skills or []))
    except Exception:
        logger.warning("Background resume parse failed for user=%s", user_id, exc_info=True)


@router.post("/resume")
async def upload_resume(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: OpenRouterClient = Depends(get_llm_client),
):
    MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large — maximum 5MB")
    filename = (file.filename or "").lower()

    if filename.endswith(".pdf"):
        resume_text = _extract_text_from_pdf(content)
    elif filename.endswith(".docx"):
        resume_text = _extract_text_from_docx(content)
    elif filename.endswith((".txt", ".tex", ".md")):
        resume_text = content.decode("utf-8", errors="replace")
    else:
        raise HTTPException(status_code=422, detail="Supported formats: PDF, DOCX, TXT, TEX")

    if not resume_text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from file")

    # Save raw text immediately so user can proceed
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.add(profile)
    profile.resume_text = resume_text
    await db.commit()

    # Parse LLM fields in background — don't block the response
    background_tasks.add_task(_parse_and_update_profile, current_user.id, resume_text, llm)

    # Return static questions immediately (no LLM wait)
    empty = ResumeParseResult(skills=[], recent_titles=[], years_of_experience=None)
    questions = generate_onboarding_questions(empty)
    return {
        "extracted": {"skills": [], "years_of_experience": None, "recent_titles": []},
        "questions": questions,
        "parsing": True,
    }


@router.get("/status")
async def onboarding_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    return {
        "onboarding_complete": profile.onboarding_complete if profile else False,
        "has_resume": bool(profile and profile.resume_text),
    }


class RefineAnswer(BaseModel):
    question_id: str
    answer: str | list[str]


@router.post("/refine")
async def refine_onboarding(
    body: RefineAnswer,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — upload resume first")

    answer = body.answer
    qid = body.question_id

    if qid == "salary_expectations":
        try:
            val = int(str(answer).replace("L", "00000").replace(",", "").replace(" ", ""))
            profile.min_salary = val
        except ValueError:
            pass
    elif qid == "target_roles":
        overrides = profile.config_overrides or {}
        overrides.setdefault("profile_intent", {})["roles"] = answer if isinstance(answer, list) else [answer]
        profile.config_overrides = overrides
    elif qid == "preferred_locations":
        overrides = profile.config_overrides or {}
        overrides.setdefault("scraping", {})["locations"] = answer if isinstance(answer, list) else [answer]
        profile.config_overrides = overrides
    elif qid == "exclusions":
        overrides = profile.config_overrides or {}
        exclusions = answer if isinstance(answer, list) else [answer]
        overrides["title_blocklist"] = exclusions
        profile.config_overrides = overrides
    elif qid == "onboarding_complete":
        profile.onboarding_complete = True

    await db.commit()
    return {"status": "saved", "question_id": qid}
