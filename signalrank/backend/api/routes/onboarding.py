import asyncio
import io
import logging
import re

from typing import Iterable

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Profile, User
from domain.resume_editor import has_resume_editor_content, merge_resume_editor, parse_resume_editor
from llm.onboarding import generate_onboarding_questions
from llm.openrouter import OpenRouterClient
from llm.resume_parser import ResumeParseResult, detect_enterprise_role_from_text, parse_resume, parse_resume_structure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


def _ai_signal_count_from_parsed(parsed: ResumeParseResult) -> int:
    ai_terms = {"ai", "ml", "mlops", "llm", "genai", "machine learning"}
    signals = 0
    if set((parsed.skills or [])).intersection({"llm", "agents", "genai", "mlops", "deep learning", "rag", "conversational ai"}):
        signals += 1
    titles_text = " ".join(parsed.recent_titles or []).lower()
    if any(term in titles_text for term in ai_terms):
        signals += 1
    resume_text = " ".join((parsed.skills or []) + (parsed.recent_titles or []))
    if any(term in resume_text.lower() for term in ai_terms):
        signals += 1
    return signals


def _suggested_roles_are_ai_only(roles: Iterable[str]) -> bool:
    ai_terms = {"ai", "ml", "genai", "agent", "mlo", "machine learning"}
    return roles and all(any(term in role.lower() for term in ai_terms) for role in roles)


def _enterprise_role(parsed: ResumeParseResult) -> str | None:
    text = " ".join((parsed.skills or []) + (parsed.recent_titles or [])).lower()
    return detect_enterprise_role_from_text(text)


def _enterprise_locations(parsed: ResumeParseResult) -> list[str] | None:
    text = (parsed.skills or []) + (parsed.recent_titles or []) + (parsed.suggested_locations or [])
    combined = " ".join(text).lower()
    if "bangalore" in combined or "bengaluru" in combined or "hyderabad" in combined or "hydrabad" in combined:
        return ["Bangalore", "Hyderabad"]
    return None


def _infer_yoe_range(years_of_experience: int | None) -> tuple[int | None, int | None]:
    if years_of_experience is None:
        return None, None
    yoe = max(0, int(years_of_experience))
    min_yoe = max(0, yoe - 2)
    max_yoe = min(30, yoe + 2)
    return min_yoe, max_yoe


def _resume_mentions_enterprise(parsed: ResumeParseResult) -> bool:
    text = " ".join((parsed.skills or []) + (parsed.recent_titles or [])).lower()
    return bool(detect_enterprise_role_from_text(text))


def _normalize_str_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _set_onboarding_parse_status(profile: Profile, status: str) -> None:
    overrides = dict(profile.config_overrides or {})
    onboarding = dict(overrides.get("onboarding") or {})
    onboarding["parse_status"] = status
    overrides["onboarding"] = onboarding
    profile.config_overrides = overrides


def _clear_stored_resume_editor(profile: Profile) -> None:
    overrides = dict(profile.config_overrides or {})
    if "resume_editor" in overrides:
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


def _apply_parsed_profile_updates(profile: Profile, parsed: ResumeParseResult) -> str | None:
    profile.skills = parsed.skills
    suggested_roles = _normalize_str_list(parsed.suggested_roles)
    suggested_locations = _normalize_str_list(parsed.suggested_locations)
    suggested_exclusions = _normalize_str_list(parsed.suggested_exclusions)
    ai_signals = _ai_signal_count_from_parsed(parsed)
    accept_suggested = suggested_roles and (
        ai_signals >= 2 or not _suggested_roles_are_ai_only(suggested_roles)
    )
    enterprise_role = _enterprise_role(parsed)
    if accept_suggested:
        profile.target_roles = suggested_roles
        profile.role_intent = suggested_roles[0]
    elif enterprise_role:
        profile.target_roles = [enterprise_role]
        profile.role_intent = enterprise_role
    elif parsed.recent_titles:
        profile.target_roles = _normalize_str_list(parsed.recent_titles)
        if profile.target_roles:
            profile.role_intent = profile.target_roles[0]
    elif _resume_mentions_enterprise(parsed):
        profile.target_roles = ["SAP SD Consultant"]
        profile.role_intent = "SAP SD Consultant"

    parts = []
    if parsed.recent_titles:
        parts.append("Recent roles: " + ", ".join(parsed.recent_titles))
    if parsed.skills:
        parts.append("Skills: " + ", ".join(parsed.skills))
    if parsed.years_of_experience:
        parts.append(f"Experience: {parsed.years_of_experience} years")

    distilled_text = "\n".join(parts) if parts else None
    if distilled_text:
        profile.distilled_text = distilled_text

    overrides = dict(profile.config_overrides or {})

    if profile.target_roles:
        overrides.setdefault("profile_intent", {})["roles"] = profile.target_roles

    if suggested_locations:
        profile.preferred_locations = suggested_locations
        overrides.setdefault("scraping", {})["locations"] = suggested_locations
    else:
        enterprise_locations = _enterprise_locations(parsed)
        if enterprise_locations:
            profile.preferred_locations = enterprise_locations
            overrides.setdefault("scraping", {})["locations"] = enterprise_locations

    if suggested_exclusions:
        overrides["title_blocklist"] = suggested_exclusions

    if overrides != (profile.config_overrides or {}):
        profile.config_overrides = overrides

    if parsed.salary_lpa:
        profile.target_lpa = float(parsed.salary_lpa)

    inferred_min_yoe, inferred_max_yoe = _infer_yoe_range(parsed.years_of_experience)
    if inferred_min_yoe is not None:
        profile.min_yoe = inferred_min_yoe
    if inferred_max_yoe is not None:
        profile.max_yoe = inferred_max_yoe

    return distilled_text


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


def _strip_icon_chars(text: str) -> str:
    import re
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


async def _parse_and_update_profile(user_id: str, resume_text: str, llm: OpenRouterClient) -> None:
    """Background task: parse resume with LLM and auto-populate profile + config_overrides."""
    distilled_text = None
    try:
        parsed_result, structure_result = await asyncio.gather(
            asyncio.wait_for(parse_resume(resume_text, llm), timeout=60),
            asyncio.wait_for(parse_resume_structure(resume_text, llm), timeout=90),
            return_exceptions=True,
        )
        parsed = parsed_result if isinstance(parsed_result, ResumeParseResult) else ResumeParseResult()
        llm_editor = structure_result if isinstance(structure_result, dict) else {}
        merged_editor = merge_resume_editor(llm_editor, parse_resume_editor(resume_text))
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = result.scalar_one_or_none()
            if not profile:
                return
            distilled_text = _apply_parsed_profile_updates(profile, parsed)
            overrides = dict(profile.config_overrides or {})
            if has_resume_editor_content(merged_editor):
                overrides["resume_editor"] = merged_editor
                profile.config_overrides = overrides
            _set_onboarding_parse_status(profile, "done")

            await db.commit()
            logger.info(
                "Background parse complete for user=%s (%d skills, roles=%s, locs=%s, editor=%s)",
                user_id, len(parsed.skills or []),
                parsed.suggested_roles, parsed.suggested_locations,
                has_resume_editor_content(merged_editor),
            )
    except Exception:
        logger.warning("Background resume parse failed for user=%s", user_id, exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Profile).where(Profile.user_id == user_id))
                profile = result.scalar_one_or_none()
                if profile:
                    _set_onboarding_parse_status(profile, "failed")
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
    _set_onboarding_parse_status(profile, "pending")
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
    elif qid == "preferred_locations":
        overrides = profile.config_overrides or {}
        cleaned_locations = _normalize_str_list(answer if isinstance(answer, list) else [answer])
        overrides.setdefault("scraping", {})["locations"] = cleaned_locations
        profile.config_overrides = overrides
        profile.preferred_locations = cleaned_locations
    elif qid == "exclusions":
        overrides = profile.config_overrides or {}
        exclusions = answer if isinstance(answer, list) else [answer]
        overrides["title_blocklist"] = exclusions
        profile.config_overrides = overrides
    elif qid == "onboarding_complete":
        profile.onboarding_complete = True

    await db.commit()
    return {"status": "saved", "question_id": qid}
