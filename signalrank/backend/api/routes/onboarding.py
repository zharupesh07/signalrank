import asyncio
import io
import logging
import re

from typing import Iterable

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import AsyncSessionLocal, ensure_runtime_schema_compatibility, get_db
from api.deps import get_current_user
from api.deps_llm import get_llm_client
from api.models import Profile, User
from domain.candidate_profile import build_candidate_profile
from domain.career_intent import build_career_intent_profile
from domain.profile_rules import infer_profile_archetypes, refine_profile_roles_for_ranking
from domain.skills import extract_skills_from_texts
from domain.resume_editor import has_resume_editor_content, merge_resume_editor, parse_resume_editor
from llm.onboarding import generate_onboarding_questions
from llm.openrouter import OpenRouterClient
from llm.resume_parser import ResumeParseResult, detect_enterprise_role_from_text, parse_resume, parse_resume_from_images, parse_resume_structure

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
        if not item or key in seen or key in {"none", "null", "nan"}:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _flatten_editor_skills(editor: dict) -> list[str]:
    skills: list[str] = []
    for group in editor.get("skills") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            text = str(item or "").strip()
            if text:
                skills.append(text)
    return _normalize_str_list(skills)


def _extract_years_from_text(text: str) -> int | None:
    matches = [
        int(match)
        for match in re.findall(r"(\d{1,2})\+?\s*(?:years?|yrs?)\b", text or "", flags=re.I)
        if match
    ]
    if not matches:
        return None
    return max(matches)


def _deterministic_resume_parse(resume_text: str, profile: Profile | None = None) -> ResumeParseResult:
    editor = parse_resume_editor(resume_text)
    resume_text_lower = (resume_text or "").lower()
    skills = _flatten_editor_skills(editor)
    if not skills and resume_text:
        cfg = {}
        skills = _normalize_str_list(extract_skills_from_texts([resume_text], cfg)[0])
    recent_titles = _normalize_str_list(
        exp.get("title")
        for exp in (editor.get("experiences") or [])[:3]
        if isinstance(exp, dict)
    )
    education = _normalize_str_list(
        edu.get("degree")
        for edu in (editor.get("education") or [])
        if isinstance(edu, dict)
    )
    locations = _normalize_str_list([editor.get("location", "")] + list(getattr(profile, "preferred_locations", None) or []))
    years = _extract_years_from_text(" ".join([resume_text, editor.get("summary", "") or ""]))
    profile_roles = _normalize_str_list([getattr(profile, "role_intent", "")] + list(getattr(profile, "target_roles", None) or []) + recent_titles)
    inferred_archetypes = infer_profile_archetypes(resume_text, profile_roles, {})
    inferred_roles = refine_profile_roles_for_ranking(profile_roles, resume_text=resume_text, archetypes=inferred_archetypes)
    archetype_role_map = {
        "sap_sd": ["SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant"],
        "ai_platform_engineer": ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"],
        "innovation_rd_engineer": ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"],
        "network_automation_engineer": ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"],
        "sap_functional": ["SAP Functional Consultant", "SAP OTC Functional Consultant", "SAP SD Consultant"],
    }
    archetype_roles: list[str] = []
    for archetype in inferred_archetypes:
        archetype_roles.extend(archetype_role_map.get(archetype, []))
    suggested_roles = _normalize_str_list(
        [getattr(profile, "role_intent", "")] + list(getattr(profile, "target_roles", None) or []) + archetype_roles + inferred_roles + recent_titles
    )
    if not suggested_roles and inferred_archetypes:
        suggested_roles = _normalize_str_list(archetype_roles or inferred_roles or recent_titles)
    if not suggested_roles:
        if detect_enterprise_role_from_text(resume_text):
            suggested_roles = ["SAP SD Consultant", "SAP OTC Functional Consultant", "SAP S/4HANA SD Consultant"]
        elif any(term in resume_text_lower for term in ("ai platform", "mlops", "llmops", "internal developer platform", "platform engineer")):
            suggested_roles = ["AI Platform Engineer", "MLOps Engineer", "ML Platform Engineer"]
        elif any(term in resume_text_lower for term in ("innovation", "emerging technolog", "prototype", "r&d", "research engineer")):
            suggested_roles = ["Innovation Engineer", "Emerging Technologies Engineer", "R&D Engineer"]
        elif any(term in resume_text_lower for term in ("network automation", "infrastructure automation", "cloud networking", "network engineer", "firewall", "load balancer")):
            suggested_roles = ["Network Automation Engineer", "Infrastructure Automation Engineer", "Cloud Network Engineer"]
    if detect_enterprise_role_from_text(resume_text):
        suggested_roles = _normalize_str_list([
            "SAP SD Consultant",
            *suggested_roles,
        ])
    elif any(term in resume_text_lower for term in ("ai platform", "mlops", "llmops", "internal developer platform", "platform engineer")):
        suggested_roles = _normalize_str_list([
            "AI Platform Engineer",
            *suggested_roles,
        ])
    elif any(term in resume_text_lower for term in ("innovation", "emerging technolog", "prototype", "r&d", "research engineer")):
        suggested_roles = _normalize_str_list([
            "Innovation Engineer",
            *suggested_roles,
        ])
    elif any(term in resume_text_lower for term in ("network automation", "infrastructure automation", "cloud networking", "network engineer", "firewall", "load balancer")):
        suggested_roles = _normalize_str_list([
            "Network Automation Engineer",
            *suggested_roles,
        ])
    career_archetypes = [
        {
            "id": archetype,
            "label": archetype.replace("_", " ").title(),
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": 0.92 if idx == 0 else 0.8,
            "evidence": ["Deterministic resume text classification"],
        }
        for idx, archetype in enumerate(inferred_archetypes[:4])
    ]
    target_roles = [
        {
            "title": role,
            "priority": "primary" if idx == 0 else "secondary",
            "confidence": 0.95 if idx == 0 else 0.85,
            "evidence": ["Deterministic resume text classification"],
        }
        for idx, role in enumerate(suggested_roles[:5])
    ]
    base_parsed = ResumeParseResult(
        skills=skills,
        years_of_experience=years,
        recent_titles=recent_titles,
        education=education,
        suggested_roles=suggested_roles[:5],
        suggested_locations=locations[:3],
        career_archetypes=career_archetypes,
        target_roles=target_roles,
    )
    career_intent = build_career_intent_profile(base_parsed)
    suggested_search_queries = _normalize_str_list(
        list((career_intent.get("query_plan") or {}).get("title_queries") or [])
        + list((career_intent.get("query_plan") or {}).get("skill_queries") or [])
        + recent_titles[:2]
    )
    suggested_exclusions = _normalize_str_list(
        [str(item.get("label", "") or "") for item in career_intent.get("negative_targets", []) if isinstance(item, dict)]
        + list((career_intent.get("query_plan") or {}).get("negative_keywords") or [])
    )
    return ResumeParseResult(
        skills=skills,
        years_of_experience=years,
        recent_titles=recent_titles,
        education=education,
        suggested_roles=suggested_roles[:5],
        suggested_locations=locations[:3],
        suggested_exclusions=suggested_exclusions[:6],
        suggested_search_queries=suggested_search_queries[:5],
        career_archetypes=career_intent.get("career_archetypes") or [],
        target_roles=career_intent.get("target_roles") or [],
        domains=career_intent.get("domains") or [],
        negative_targets=career_intent.get("negative_targets") or [],
        false_friend_terms=career_intent.get("false_friend_terms") or [],
        query_plan=career_intent.get("query_plan") or {},
        ambiguities=career_intent.get("ambiguities") or [],
        follow_up_questions=career_intent.get("follow_up_questions") or [],
    )


def _candidate_profile_confidence(candidate_profile: dict | None) -> float:
    if not isinstance(candidate_profile, dict):
        return 0.0
    confidence = candidate_profile.get("confidence_by_field", {})
    if isinstance(confidence, dict):
        try:
            return float(confidence.get("overall") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _should_run_onboarding_llm(candidate_profile: dict | None, parsed: ResumeParseResult) -> bool:
    if not candidate_profile:
        return True
    if len(parsed.recent_titles or []) == 0 or len(parsed.skills or []) == 0:
        return True
    if len(candidate_profile.get("ambiguities") or []) > 0:
        return True
    return _candidate_profile_confidence(candidate_profile) < 0.6


def _sync_career_intent_override(profile: Profile) -> None:
    overrides = dict(profile.config_overrides or {})
    career_intent = dict(overrides.get("career_intent") or {})
    work_preferences = dict(career_intent.get("work_preferences") or {})
    query_plan = dict(career_intent.get("query_plan") or {})

    if profile.target_roles:
        career_intent["target_roles"] = [
            {
                "title": role,
                "priority": "primary" if idx == 0 else "secondary",
                "confidence": 0.9 if idx == 0 else 0.75,
                "evidence": ["User-confirmed target role"],
            }
            for idx, role in enumerate(_normalize_str_list(profile.target_roles))
        ]
        query_plan["title_queries"] = _normalize_str_list(query_plan.get("title_queries", []) + list(profile.target_roles))

    if profile.preferred_locations:
        work_preferences["locations"] = _normalize_str_list(profile.preferred_locations)

    title_blocklist = _normalize_str_list(overrides.get("title_blocklist") or [])
    if title_blocklist:
        career_intent["negative_targets"] = [
            {
                "label": label,
                "reason": "User-specified exclusion",
                "confidence": 1.0,
            }
            for label in title_blocklist
        ]
        query_plan["negative_keywords"] = title_blocklist

    career_intent["work_preferences"] = work_preferences
    career_intent["query_plan"] = query_plan
    overrides["career_intent"] = career_intent
    profile.config_overrides = overrides


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
    career_intent = build_career_intent_profile(parsed)
    suggested_roles = _normalize_str_list(parsed.suggested_roles)
    suggested_locations = _normalize_str_list(parsed.suggested_locations)
    suggested_exclusions = _normalize_str_list(parsed.suggested_exclusions)
    explicit_target_roles = _normalize_str_list(
        role.get("title")
        for role in career_intent.get("target_roles", [])
        if isinstance(role, dict)
    )
    structured_locations = _normalize_str_list(
        ((career_intent.get("work_preferences") or {}).get("locations")) or []
    )
    structured_negatives = _normalize_str_list(
        target.get("label")
        for target in career_intent.get("negative_targets", [])
        if isinstance(target, dict)
    )
    query_plan = dict(career_intent.get("query_plan") or {})
    ai_signals = _ai_signal_count_from_parsed(parsed)
    accept_suggested = suggested_roles and (
        ai_signals >= 2 or not _suggested_roles_are_ai_only(suggested_roles)
    )
    enterprise_role = _enterprise_role(parsed)
    if explicit_target_roles:
        profile.target_roles = explicit_target_roles
        profile.role_intent = explicit_target_roles[0]
    elif accept_suggested:
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
    overrides["career_intent"] = career_intent

    if profile.target_roles:
        overrides.setdefault("profile_intent", {})["roles"] = profile.target_roles

    if structured_locations:
        profile.preferred_locations = structured_locations
        overrides.setdefault("scraping", {})["locations"] = structured_locations
    elif suggested_locations:
        profile.preferred_locations = suggested_locations
        overrides.setdefault("scraping", {})["locations"] = suggested_locations
    else:
        enterprise_locations = _enterprise_locations(parsed)
        if enterprise_locations:
            profile.preferred_locations = enterprise_locations
            overrides.setdefault("scraping", {})["locations"] = enterprise_locations

    if structured_negatives:
        overrides["title_blocklist"] = structured_negatives
    elif suggested_exclusions:
        overrides["title_blocklist"] = suggested_exclusions

    suggested_search_queries = _normalize_str_list(parsed.suggested_search_queries)
    query_terms = _normalize_str_list(
        (query_plan.get("title_queries") or [])
        + (query_plan.get("skill_queries") or [])
        + (query_plan.get("domain_queries") or [])
    )
    if query_terms:
        profile.custom_search_queries = query_terms
    elif suggested_search_queries:
        profile.custom_search_queries = suggested_search_queries

    if overrides != (profile.config_overrides or {}):
        profile.config_overrides = overrides

    if parsed.salary_lpa:
        profile.target_lpa = float(parsed.salary_lpa)

    inferred_min_yoe, inferred_max_yoe = _infer_yoe_range(parsed.years_of_experience)
    if inferred_min_yoe is not None:
        profile.min_yoe = inferred_min_yoe
    if inferred_max_yoe is not None:
        profile.max_yoe = inferred_max_yoe

    _sync_career_intent_override(profile)
    profile.candidate_profile = build_candidate_profile(
        parsed=parsed,
        profile=profile,
        resume_text=profile.resume_text,
    )
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
            distilled = _apply_parsed_profile_updates(profile, parsed)
            overrides = dict(profile.config_overrides or {})
            merged = merge_resume_editor(merged_editor, existing_editor)
            if has_resume_editor_content(merged):
                overrides["resume_editor"] = merged
                profile.config_overrides = overrides
            _set_onboarding_parse_status(profile, "done")
            await db.commit()
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
        try:
            distilled_text, merged_editor = await _commit_profile_changes()
        except Exception as exc:
            if "UndefinedColumnError" not in str(exc) and "does not exist" not in str(exc):
                raise
            await ensure_runtime_schema_compatibility()
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
    _apply_parsed_profile_updates(profile, deterministic_parsed)

    should_run_llm = _should_run_onboarding_llm(profile.candidate_profile, deterministic_parsed)
    _set_onboarding_parse_status(profile, "pending" if should_run_llm else "done")
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
