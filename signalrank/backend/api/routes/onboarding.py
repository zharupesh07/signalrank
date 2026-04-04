import asyncio
import io
import logging
import re

from typing import Iterable

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, commit_with_runtime_schema_compatibility, get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Profile, User
from domain.onboarding_profile import (
    apply_parsed_profile_updates,
    build_profile_patch,
    deterministic_resume_parse,
    merge_profile_patch,
    should_run_onboarding_llm,
)
from domain.skills import extract_skills_from_texts
from domain.resume_editor import has_resume_editor_content, merge_resume_editor, parse_resume_editor
from llm.onboarding import generate_onboarding_questions
from llm.openrouter import OpenRouterClient
from llm.resume_parser import ResumeParseResult, parse_resume, parse_resume_from_images, parse_resume_structure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _deterministic_resume_parse(resume_text: str, profile: Profile | None = None) -> ResumeParseResult:
    return deterministic_resume_parse(resume_text, profile)


def _clear_stored_resume_editor(profile: Profile) -> None:
    overrides = dict(profile.config_overrides or {})
    overrides.pop("resume_editor", None)
    profile.config_overrides = overrides or None


def _parse_salary_to_number(value: str | list[str]) -> int | None:
    text = " ".join(value) if isinstance(value, list) else str(value)
    normalized = text.strip().lower().replace(",", "")
    if not normalized:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    amount = float(match.group(1))
    if "cr" in normalized or "crore" in normalized:
        return int(amount * 10000000)
    if "lpa" in normalized or re.search(r"\bl\b", normalized):
        return int(amount * 100000)
    if amount < 1000:
        return int(amount * 100000)
    return int(amount)


def _extract_text_from_pdf(content: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        all_lines: list[str] = []
        for page in doc:
            blocks = page.get_text("blocks")
            text_blocks = [b for b in blocks if b[6] == 0]
            if not text_blocks:
                continue
            mid_x = page.rect.width / 2
            wide = [b for b in text_blocks if b[0] < mid_x - 20 and b[2] > mid_x + 20]
            narrow = [b for b in text_blocks if b not in wide]
            left = [b for b in narrow if b[2] <= mid_x + 20]
            right = [b for b in narrow if b[0] >= mid_x - 20]
            is_two_col = bool(left) and bool(right) and len(left) >= 3 and len(right) >= 3
            if is_two_col:
                # Header (full-width) blocks first, then left column, then right column
                wide.sort(key=lambda b: (b[1], b[0]))
                for b in wide:
                    for line in b[4].splitlines():
                        cleaned = _strip_icon_chars(line).strip()
                        if cleaned:
                            all_lines.append(cleaned)
                for col in (left, right):
                    col.sort(key=lambda b: (b[1], b[0]))
                    for b in col:
                        for line in b[4].splitlines():
                            cleaned = _strip_icon_chars(line).strip()
                            if cleaned:
                                all_lines.append(cleaned)
            else:
                text_blocks.sort(key=lambda b: (b[1], b[0]))
                for b in text_blocks:
                    for line in b[4].splitlines():
                        cleaned = _strip_icon_chars(line).strip()
                        if cleaned:
                            all_lines.append(cleaned)
        doc.close()
        return "\n".join(all_lines)
    except Exception as e:
        logger.warning("PyMuPDF extraction failed, falling back to pypdf: %s", e)
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            return ""


def _render_pdf_pages_as_images(content: bytes, dpi: int = 120) -> list[bytes]:
    """Render each page of a PDF as a PNG image at the given DPI.

    Returns a list of PNG bytes, one per page.  Used for vision-LLM parsing.
    Falls back to empty list on any error so the caller can use text extraction.
    """
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        pages: list[bytes] = []
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pages.append(pix.tobytes("png"))
        doc.close()
        return pages
    except Exception as e:
        logger.warning("PDF page render failed: %s", e)
        return []


def _strip_icon_chars(text: str) -> str:
    return re.sub(r"[\ue000-\uf8ff]", "", text)


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
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile:
                return
            cache = PgEmbeddingCache(db, ctx.config_fp)
            cached = await cache.fetch([resume_fp])
            if resume_fp in cached:
                profile.resume_embedding = list(cached[resume_fp])
            else:
                engine = EmbeddingEngine(cfg)
                r_emb = engine.embed([resume_emb_text])[0]
                await cache.store_vectors([(resume_fp, r_emb.tolist())])
                profile.resume_embedding = r_emb.tolist()
                logger.info("[EMBED] Pre-cached resume embedding for user=%s", user_id)
            await db.commit()
    except Exception:
        logger.warning("Resume embedding pre-cache failed for user=%s", user_id, exc_info=True)


async def _parse_and_update_profile(
    user_id: str,
    resume_text: str,
    llm: OpenRouterClient,
    *,
    pdf_bytes: bytes | None = None,
) -> None:
    """Background task: parse resume with LLM and auto-populate profile + config_overrides.

    If ``pdf_bytes`` is provided, attempts vision-based parsing first (renders
    PDF pages as images and sends to a free vision model).  Falls back to
    text-based LLM parsing if vision fails or is unavailable.
    """
    distilled_text = None
    async def _commit_profile_changes() -> tuple[str | None, dict]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile:
                return None, {}
            existing_editor = None
            if isinstance(profile.config_overrides, dict):
                candidate = profile.config_overrides.get("resume_editor")
                if isinstance(candidate, dict):
                    existing_editor = candidate
            distilled = apply_parsed_profile_updates(profile, parsed)
            overrides = dict(profile.config_overrides or {})
            merged = merge_resume_editor(merged_editor, existing_editor)
            if has_resume_editor_content(merged):
                overrides["resume_editor"] = merged
                profile.config_overrides = overrides
            profile.config_overrides = merge_profile_patch(profile.config_overrides, build_profile_patch(parse_status="done"))
            await commit_with_runtime_schema_compatibility(db)
            return distilled, merged

    try:
        # Step 1: Text-first — two parallel LLM calls on extracted text.
        # No images, no hallucination risk. Fast (~2s each).
        parsed_result, structure_result = await asyncio.gather(
            asyncio.wait_for(parse_resume(resume_text, llm), timeout=60),
            asyncio.wait_for(parse_resume_structure(resume_text, llm), timeout=90),
            return_exceptions=True,
        )
        parsed = parsed_result if isinstance(parsed_result, ResumeParseResult) else ResumeParseResult()
        llm_editor = structure_result if isinstance(structure_result, dict) else {}

        # Step 2: Vision fallback — only when text parse is weak.
        # Triggers for image-heavy/scanned PDFs where text extraction fails.
        text_has_content = (
            len(llm_editor.get("experiences", [])) >= 2
            and llm_editor.get("name")
        )
        if pdf_bytes and not text_has_content:
            page_images = _render_pdf_pages_as_images(pdf_bytes)
            if page_images:
                logger.info("Text parse weak (exps=%d, name=%r) — trying vision fallback",
                            len(llm_editor.get("experiences", [])), llm_editor.get("name"))
                vision_editor = await asyncio.wait_for(
                    parse_resume_from_images(
                        page_images, llm,
                        reference_text=resume_text,
                    ),
                    timeout=180,
                )
                if vision_editor and len(vision_editor.get("experiences", [])) > len(llm_editor.get("experiences", [])):
                    llm_editor = vision_editor

        from domain.resume_verifier import verify_against_reference
        llm_editor = verify_against_reference(llm_editor, resume_text)
        merged_editor = merge_resume_editor(llm_editor, parse_resume_editor(resume_text))
        distilled_text, merged_editor = await _commit_profile_changes()

        logger.info(
            "Background parse complete for user=%s (%d skills, roles=%s, locs=%s, queries=%s, editor=%s)",
            user_id, len(parsed.skills or []),
            parsed.suggested_roles, parsed.suggested_locations,
            parsed.suggested_search_queries,
            has_resume_editor_content(merged_editor),
        )
    except Exception:
        logger.warning("Background resume parse failed for user=%s", user_id, exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Profile).where(Profile.user_id == user_id))
                profile = result.scalar_one_or_none()
                if profile:
                    profile.config_overrides = merge_profile_patch(profile.config_overrides, build_profile_patch(parse_status="failed"))
                    await db.commit()
        except Exception:
            logger.warning("Failed to record parse failure for user=%s", user_id, exc_info=True)
        return

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

    pdf_bytes: bytes | None = None
    if filename.endswith(".pdf"):
        pdf_bytes = content
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
    result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.id).with_for_update()
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.add(profile)
        await db.flush()
    profile.resume_text = resume_text
    profile.resume_embedding = None
    _clear_stored_resume_editor(profile)
    deterministic_parsed = _deterministic_resume_parse(resume_text, profile)
    deterministic_editor = parse_resume_editor(resume_text)
    if has_resume_editor_content(deterministic_editor):
        overrides = dict(profile.config_overrides or {})
        overrides["resume_editor"] = deterministic_editor
        profile.config_overrides = overrides
    apply_parsed_profile_updates(profile, deterministic_parsed)

    should_run_llm = should_run_onboarding_llm(profile.candidate_profile, deterministic_parsed)
    patch = build_profile_patch(parse_status="pending" if should_run_llm else "done")
    profile.config_overrides = merge_profile_patch(profile.config_overrides, patch)
    await db.commit()

    if should_run_llm:
        # Parse LLM fields in background — don't block the response.
        # Pass pdf_bytes so vision-LLM parsing can be attempted first.
        background_tasks.add_task(
            _parse_and_update_profile, current_user.id, resume_text, llm, pdf_bytes=pdf_bytes
        )

    questions = generate_onboarding_questions(deterministic_parsed)
    return {
        "extracted": {
            "skills": deterministic_parsed.skills,
            "years_of_experience": deterministic_parsed.years_of_experience,
            "recent_titles": deterministic_parsed.recent_titles,
        },
        "questions": questions,
        "parsing": should_run_llm,
    }


@router.get("/parsed")
async def onboarding_parsed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll this after resume upload to get LLM-extracted pre-fill values."""
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.resume_text:
        return {"parsing": True, "prefill": {}}

    overrides = profile.config_overrides or {}
    parse_status = (overrides.get("onboarding") or {}).get("parse_status")
    if parse_status not in {"done", "failed"}:
        return {"parsing": True, "prefill": {}}
    if parse_status == "failed":
        return {"parsing": False, "prefill": {}}

    return {
        "parsing": False,
        "prefill": {
            "target_roles": overrides.get("profile_intent", {}).get("roles", []),
            "preferred_locations": overrides.get("scraping", {}).get("locations", []),
            "exclusions": overrides.get("title_blocklist", []),
            "career_intent": overrides.get("career_intent", {}),
            "salary_lpa": int(profile.target_lpa) if profile.target_lpa else None,
            "min_yoe": profile.min_yoe,
            "max_yoe": profile.max_yoe,
            "role_intent": profile.role_intent,
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
            val = _parse_salary_to_number(answer)
            if val is not None:
                profile.min_salary = val
        except ValueError:
            pass
    elif qid == "target_roles":
        overrides = profile.config_overrides or {}
        raw_roles = answer if isinstance(answer, list) else [answer]
        cleaned_roles = _normalize_str_list(raw_roles)
        overrides.setdefault("profile_intent", {})["roles"] = cleaned_roles
        profile.config_overrides = overrides
        profile.target_roles = cleaned_roles
        if cleaned_roles:
            profile.role_intent = cleaned_roles[0]
        _sync_career_intent_override(profile)
    elif qid == "preferred_locations":
        overrides = profile.config_overrides or {}
        cleaned_locations = _normalize_str_list(answer if isinstance(answer, list) else [answer])
        overrides.setdefault("scraping", {})["locations"] = cleaned_locations
        profile.config_overrides = overrides
        profile.preferred_locations = cleaned_locations
        _sync_career_intent_override(profile)
    elif qid == "exclusions":
        overrides = profile.config_overrides or {}
        exclusions = answer if isinstance(answer, list) else [answer]
        overrides["title_blocklist"] = _normalize_str_list(exclusions)
        profile.config_overrides = overrides
        _sync_career_intent_override(profile)
    elif qid == "onboarding_complete":
        profile.onboarding_complete = True

    profile.candidate_profile = build_candidate_profile(profile=profile)
    await db.commit()
    return {"status": "saved", "question_id": qid}
