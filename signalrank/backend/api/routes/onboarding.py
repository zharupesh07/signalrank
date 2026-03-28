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


async def _embed_resume(user_id: str, resume_text: str, distilled_text: str | None) -> None:
    """Pre-compute and cache resume embedding so ranking gets a 100% cache hit."""
    import domain.embeddings as _emb_mod
    from batch.context import build_context
    from batch.embedding_cache import PgEmbeddingCache
    from domain.embeddings import (
        EmbeddingEngine,
        build_resume_embedding_text,
        fingerprint_text,
    )

    try:
        ctx = build_context(user_id=user_id, resume_text=resume_text)
        cfg = ctx.config
        resume_emb_text = build_resume_embedding_text(
            resume_text=resume_text,
            distilled=distilled_text or cfg.get("resume", {}).get("distilled_text"),
            cfg=cfg,
            use_case="default",
        )
        resume_fp = fingerprint_text(resume_emb_text)

        async with AsyncSessionLocal() as db:
            cache = PgEmbeddingCache(db, ctx.config_fp)
            cached = await cache.fetch([resume_fp])
            if resume_fp not in cached:
                engine = EmbeddingEngine(cfg)
                r_emb = engine.embed([resume_emb_text])[0]
                await cache.store_vectors([(resume_fp, r_emb.tolist())])
                await db.commit()
                logger.info("[EMBED] Pre-cached resume embedding for user=%s", user_id)
    except Exception:
        logger.warning("Resume embedding pre-cache failed for user=%s", user_id, exc_info=True)


async def _parse_and_update_profile(user_id: str, resume_text: str, llm: OpenRouterClient) -> None:
    """Background task: parse resume with LLM and auto-populate profile + config_overrides."""
    distilled_text = None
    try:
        parsed = await asyncio.wait_for(parse_resume(resume_text, llm), timeout=60)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile:
                return

            profile.skills = parsed.skills
            if parsed.recent_titles and not profile.target_roles:
                profile.target_roles = parsed.recent_titles

            parts = []
            if parsed.recent_titles:
                parts.append("Recent roles: " + ", ".join(parsed.recent_titles))
            if parsed.skills:
                parts.append("Skills: " + ", ".join(parsed.skills))
            if parsed.years_of_experience:
                parts.append(f"Experience: {parsed.years_of_experience} years")
            if parts:
                distilled_text = "\n".join(parts)
                profile.distilled_text = distilled_text

            # Auto-populate config_overrides from LLM extractions (only if not already set by user)
            overrides = dict(profile.config_overrides or {})

            if parsed.suggested_roles and not overrides.get("profile_intent", {}).get("roles"):
                overrides.setdefault("profile_intent", {})["roles"] = parsed.suggested_roles

            if parsed.suggested_locations and not overrides.get("scraping", {}).get("locations"):
                overrides.setdefault("scraping", {})["locations"] = parsed.suggested_locations

            if parsed.suggested_exclusions and not overrides.get("title_blocklist"):
                overrides["title_blocklist"] = parsed.suggested_exclusions

            if overrides != (profile.config_overrides or {}):
                profile.config_overrides = overrides

            if parsed.salary_lpa and not profile.target_lpa:
                profile.target_lpa = float(parsed.salary_lpa)

            await db.commit()
            logger.info(
                "Background parse complete for user=%s (%d skills, roles=%s, locs=%s)",
                user_id, len(parsed.skills or []),
                parsed.suggested_roles, parsed.suggested_locations,
            )
    except Exception:
        logger.warning("Background resume parse failed for user=%s", user_id, exc_info=True)

    await _embed_resume(user_id, resume_text, distilled_text)


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


@router.get("/parsed")
async def onboarding_parsed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll this after resume upload to get LLM-extracted pre-fill values."""
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.skills:
        return {"parsing": True, "prefill": {}}

    overrides = profile.config_overrides or {}
    return {
        "parsing": False,
        "prefill": {
            "target_roles": overrides.get("profile_intent", {}).get("roles", []),
            "preferred_locations": overrides.get("scraping", {}).get("locations", []),
            "exclusions": overrides.get("title_blocklist", []),
            "salary_lpa": int(profile.target_lpa) if profile.target_lpa else None,
        },
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
