from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, Profile, Run, User
from batch.context import build_context
from batch.embedding_cache import PgEmbeddingCache, store_job_embeddings
from batch.run_results import persist_ranked_results
from domain.embeddings import EmbeddingEngine, build_job_embedding_text, fingerprint_text
from domain.job_profile import build_job_profile
from domain.role_clusters import infer_clusters_from_job_text
from domain.skills import SkillCanonicalizer, extract_skills_from_texts
from ranking.v4.db_scorer import score_jobs_for_user

logger = logging.getLogger(__name__)

_PIPELINE_LINE_RE = re.compile(r"^\s*-\s*\[(?P<checked>[ xX])\]\s+(?P<ref>[^|]+?)\s*\|\s*(?P<company>[^|]+?)\s*\|\s*(?P<title>.+?)\s*$")
_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_HTTP_TIMEOUT = 20.0
_MAX_DESCRIPTION_CHARS = 12_000
_REMOTE_FETCH_CONCURRENCY = 12
_MAX_TITLE_LENGTH = 500
_MAX_COMPANY_LENGTH = 255
_MAX_LOCATION_LENGTH = 255
_MAX_SITE_LENGTH = 100


@dataclass(slots=True)
class CareerOpsCandidate:
    source_ref: str
    canonical_job_url: str
    title: str
    company: str
    checked: bool
    is_local_jd: bool
    local_path: Path | None = None


@dataclass(slots=True)
class EnrichedCareerOpsJob:
    source_ref: str
    job_url: str
    title: str
    company: str
    location: str | None
    description: str
    site: str
    date_posted: datetime | None
    role_clusters: list[str]
    job_profile: dict[str, Any]


@dataclass(slots=True)
class CareerOpsImportSummary:
    workspace_path: str
    user_email: str
    candidate_count: int
    imported_count: int
    inserted_count: int
    updated_count: int
    scored_count: int
    skipped_count: int
    run_id: str | None
    imported_job_urls: list[str]
    errors: list[str]


def _manual_job_url(workspace_path: Path, local_ref: str) -> str:
    digest = sha1(str(workspace_path.resolve()).encode("utf-8")).hexdigest()[:12]
    normalized = local_ref.replace("\\", "/").strip("/")
    return f"manual://career-ops/{digest}/{normalized}"


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate(value: str | None, limit: int) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    return cleaned[:limit]


def _strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _clean_text(soup.get_text(" "))


def _slug_to_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"_+(?:JR|R)[-_]?[A-Za-z0-9-]+$", "", text, flags=re.I)
    text = re.sub(r"[-_]+(?:JR|R)[-_]?[A-Za-z0-9-]+$", "", text, flags=re.I)
    text = text.replace("---", " ").replace("--", " ")
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" /")
    return text


def _normalize_location_hint(value: str) -> str | None:
    text = _slug_to_text(value)
    if not text:
        return None
    replacements = {
        "ind": "India",
        "bengaluru": "Bengaluru",
        "bangalore": "Bangalore",
        "pune": "Pune",
        "india": "India",
    }
    parts = []
    for token in text.split():
        lowered = token.lower()
        if token.isupper() and lowered not in replacements:
            parts.append(token)
            continue
        parts.append(replacements.get(lowered, token))
    if "India" in parts and any(city in parts for city in ("Pune", "Bangalore", "Bengaluru")):
        city = next(city for city in ("Pune", "Bangalore", "Bengaluru") if city in parts)
        return f"{city}, India"
    normalized = " ".join(parts)
    normalized = re.sub(r"\bIndia\b", ", India", normalized, count=1)
    normalized = re.sub(r"\s+,", ",", normalized)
    return normalized[:_MAX_LOCATION_LENGTH]


def _parse_job_url_hints(job_url: str) -> dict[str, str | None]:
    parsed = urlparse(job_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 3 or path_parts[0].lower() != "job":
        return {"title": None, "location": None}

    location_hint = _normalize_location_hint(path_parts[1])
    title_hint = _slug_to_text(path_parts[2])
    return {
        "title": title_hint or None,
        "location": location_hint,
    }


def _is_generic_careers_page_title(title: str, company: str) -> bool:
    lowered = _clean_text(title).lower()
    company_lower = _clean_text(company).lower()
    if not lowered:
        return True
    generic_markers = (
        "careers at",
        "working at",
        "careers",
        "jobs",
        "discover career opportunities",
    )
    if any(marker in lowered for marker in generic_markers):
        return True
    return bool(company_lower and lowered in {company_lower, f"{company_lower} careers", f"careers at {company_lower}"})


def _is_generic_careers_page_description(description: str) -> bool:
    lowered = _clean_text(description).lower()
    if not lowered:
        return True
    generic_phrases = (
        "find your dream job",
        "browse available job openings",
        "discover career opportunities",
        "boost your career",
        "kickstart your",
        "redefine the future of finance",
        "join our teams",
    )
    return any(phrase in lowered for phrase in generic_phrases)


def _looks_like_shell_copy(description: str, fallback_title: str) -> bool:
    cleaned = _clean_text(description)
    if not cleaned:
        return True
    lowered = cleaned.lower()
    fallback_lower = _clean_text(fallback_title).lower()
    if fallback_lower and fallback_lower in lowered:
        return False
    return len(cleaned) < 120


def _normalize_extracted_title(title: str, fallback_title: str) -> str:
    cleaned = _clean_text(title)
    if re.match(r"^job application for\b", cleaned, re.I):
        cleaned = re.sub(r"^job application for\s+", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"\s+at\s+.+$", "", cleaned, flags=re.I).strip()
    return cleaned or _clean_text(fallback_title)


def _parse_iso_date(value: str | None) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        match = _DATE_RE.search(text)
        if not match:
            return None
        parsed = datetime.fromisoformat(match.group(1))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.text or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            payloads.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            payloads.append(data)
    return payloads


def _extract_location_from_json_ld(payload: dict[str, Any]) -> str | None:
    locations: list[str] = []

    def _append_value(value: Any) -> None:
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                locations.append(cleaned)
        elif isinstance(value, dict):
            for key in ("addressLocality", "addressRegion", "addressCountry", "streetAddress", "name"):
                _append_value(value.get(key))
            address = value.get("address")
            if isinstance(address, dict):
                _append_value(address)
        elif isinstance(value, list):
            for item in value:
                _append_value(item)

    _append_value(payload.get("jobLocation"))
    _append_value(payload.get("applicantLocationRequirements"))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in locations:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ", ".join(ordered) or None


def _extract_remote_hint(payload: dict[str, Any]) -> str | None:
    text = json.dumps(payload, default=str).lower()
    if "telecommute" in text or "remote" in text:
        return "Remote"
    return None


def _extract_job_posting_fields(html: str, fallback_title: str, fallback_company: str, job_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    json_ld = _json_ld_objects(soup)
    url_hints = _parse_job_url_hints(job_url)
    used_json_ld = False

    extracted: dict[str, Any] = {
        "title": "",
        "company": "",
        "location": None,
        "description": "",
        "date_posted": None,
    }

    for payload in json_ld:
        payload_type = str(payload.get("@type") or payload.get("['@type']") or "").lower()
        if "jobposting" not in payload_type:
            continue
        used_json_ld = True
        extracted["title"] = _clean_text(payload.get("title")) or extracted["title"]
        org = payload.get("hiringOrganization")
        if isinstance(org, dict):
            extracted["company"] = _clean_text(org.get("name")) or extracted["company"]
        extracted["location"] = (
            _extract_location_from_json_ld(payload)
            or _extract_remote_hint(payload)
            or extracted["location"]
        )
        description_html = payload.get("description")
        if isinstance(description_html, str) and description_html.strip():
            extracted["description"] = _strip_html(description_html)[:_MAX_DESCRIPTION_CHARS]
        extracted["date_posted"] = _parse_iso_date(payload.get("datePosted")) or extracted["date_posted"]
        break

    if not extracted["title"]:
        extracted["title"] = _clean_text(
            soup.title.string if soup.title and soup.title.string else ""
        )
    if not extracted["company"]:
        meta_site = soup.find("meta", attrs={"property": "og:site_name"})
        extracted["company"] = _clean_text(fallback_company or (meta_site.get("content") if meta_site else ""))

    if not extracted["description"]:
        extracted["description"] = _strip_html(html)[:_MAX_DESCRIPTION_CHARS]

    title_was_generic = _is_generic_careers_page_title(extracted["title"], fallback_company)
    if title_was_generic:
        extracted["title"] = _clean_text(url_hints.get("title")) or ""

    if not extracted["location"]:
        extracted["location"] = _clean_text(url_hints.get("location")) or None

    if _is_generic_careers_page_description(extracted["description"]) or (
        title_was_generic and not used_json_ld and _looks_like_shell_copy(extracted["description"], fallback_title)
    ):
        synthetic_parts = [
            _clean_text(extracted["title"] or fallback_title),
            f"Company: {_clean_text(extracted['company'] or fallback_company)}" if _clean_text(extracted["company"] or fallback_company) else "",
            f"Location: {_clean_text(extracted['location'])}" if _clean_text(extracted["location"]) else "",
            "Imported from a branded career page where the job-specific description was not available in the fetched HTML.",
        ]
        extracted["description"] = _clean_text(" ".join(part for part in synthetic_parts if part))[:_MAX_DESCRIPTION_CHARS]

    extracted["title"] = _normalize_extracted_title(extracted["title"], fallback_title)
    extracted["company"] = _clean_text(extracted["company"] or fallback_company)
    return extracted


def _detect_site(candidate: CareerOpsCandidate) -> str:
    if candidate.is_local_jd:
        return "manual"

    host = (urlparse(candidate.canonical_job_url).hostname or "").lower()
    if "greenhouse" in host:
        return "greenhouse"
    if "ashbyhq.com" in host:
        return "ashby"
    if "lever.co" in host:
        return "lever"
    return "company"


def _parse_scan_history(scan_history_path: Path) -> dict[str, dict[str, str]]:
    if not scan_history_path.exists():
        return {}

    entries: dict[str, dict[str, str]] = {}
    for line in scan_history_path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 5:
            continue
        url, first_seen, _, title, company = cols[:5]
        entries[url] = {
            "first_seen": first_seen.strip(),
            "title": _clean_text(title),
            "company": _clean_text(company),
        }
    return entries


def parse_career_ops_pipeline(workspace_path: str | Path, *, pending_only: bool = False) -> list[CareerOpsCandidate]:
    workspace = Path(workspace_path)
    pipeline_path = workspace / "data" / "pipeline.md"
    if not pipeline_path.exists():
        raise FileNotFoundError(f"Career-Ops pipeline not found: {pipeline_path}")

    candidates: list[CareerOpsCandidate] = []
    for raw_line in pipeline_path.read_text(encoding="utf-8").splitlines():
        match = _PIPELINE_LINE_RE.match(raw_line)
        if not match:
            continue
        checked = match.group("checked").lower() == "x"
        if pending_only and checked:
            continue

        source_ref = _clean_text(match.group("ref"))
        company = _clean_text(match.group("company"))
        title = _clean_text(match.group("title"))
        if not source_ref or not company or not title:
            continue

        is_local = source_ref.startswith("local:")
        local_path: Path | None = None
        canonical_job_url = source_ref
        if is_local:
            local_rel = source_ref[len("local:"):].strip()
            local_path = workspace / local_rel
            canonical_job_url = _manual_job_url(workspace, local_rel)

        candidates.append(
            CareerOpsCandidate(
                source_ref=source_ref,
                canonical_job_url=canonical_job_url,
                title=title,
                company=company,
                checked=checked,
                is_local_jd=is_local,
                local_path=local_path,
            )
        )

    return candidates


def _infer_role_clusters(title: str, description: str, preferred: list[str] | None = None) -> list[str]:
    if preferred:
        return sorted(dict.fromkeys(preferred))
    return sorted(infer_clusters_from_job_text(title or None, description or None))


async def _enrich_remote_candidate(
    candidate: CareerOpsCandidate,
    *,
    scan_meta: dict[str, dict[str, str]],
    client: httpx.AsyncClient,
    cfg: dict,
) -> EnrichedCareerOpsJob:
    response = await client.get(
        candidate.canonical_job_url,
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
    )
    response.raise_for_status()
    fields = _extract_job_posting_fields(
        response.text,
        candidate.title,
        candidate.company,
        candidate.canonical_job_url,
    )
    meta = scan_meta.get(candidate.canonical_job_url, {})
    title = fields["title"] or meta.get("title") or candidate.title
    company = fields["company"] or meta.get("company") or candidate.company
    date_posted = fields["date_posted"] or _parse_iso_date(meta.get("first_seen"))
    location = _clean_text(fields.get("location")) or None
    description = _clean_text(fields["description"])
    role_clusters = _infer_role_clusters(title, description)
    job_profile = build_job_profile(
        title=title,
        company=company,
        description=description,
        location=location,
        site=_detect_site(candidate),
        date_posted=date_posted,
        role_clusters=role_clusters,
        cfg=cfg,
    )
    return EnrichedCareerOpsJob(
        source_ref=candidate.source_ref,
        job_url=candidate.canonical_job_url,
        title=title,
        company=company,
        location=location,
        description=description,
        site=_detect_site(candidate),
        date_posted=date_posted,
        role_clusters=role_clusters,
        job_profile=job_profile,
    )


def _extract_location_from_text(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:20]:
        lower = line.lower()
        if "remote" in lower:
            return "Remote"
        if any(city in lower for city in ("bangalore", "bengaluru", "pune", "hyderabad", "mumbai", "india")):
            return line[:255]
    return None


def _build_local_job(candidate: CareerOpsCandidate, *, cfg: dict) -> EnrichedCareerOpsJob:
    if candidate.local_path is None or not candidate.local_path.exists():
        raise FileNotFoundError(f"Local JD not found: {candidate.local_path}")

    text = candidate.local_path.read_text(encoding="utf-8")
    location = _extract_location_from_text(text)
    description = _clean_text(text)[:_MAX_DESCRIPTION_CHARS]
    date_posted = None
    role_clusters = _infer_role_clusters(candidate.title, description)
    job_profile = build_job_profile(
        title=candidate.title,
        company=candidate.company,
        description=description,
        location=location,
        site="manual",
        date_posted=date_posted,
        role_clusters=role_clusters,
        cfg=cfg,
    )
    return EnrichedCareerOpsJob(
        source_ref=candidate.source_ref,
        job_url=candidate.canonical_job_url,
        title=candidate.title,
        company=candidate.company,
        location=location,
        description=description,
        site="manual",
        date_posted=date_posted,
        role_clusters=role_clusters,
        job_profile=job_profile,
    )


async def enrich_career_ops_candidates(
    candidates: list[CareerOpsCandidate],
    *,
    workspace_path: str | Path,
    config_overrides: dict | None = None,
) -> tuple[list[EnrichedCareerOpsJob], list[str]]:
    workspace = Path(workspace_path)
    ctx = build_context("__career_ops_import__", "", config_overrides)
    scan_meta = _parse_scan_history(workspace / "data" / "scan-history.tsv")
    enriched: list[EnrichedCareerOpsJob] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        semaphore = asyncio.Semaphore(_REMOTE_FETCH_CONCURRENCY)

        async def _enrich_one(candidate: CareerOpsCandidate) -> tuple[EnrichedCareerOpsJob | None, str | None]:
            try:
                if candidate.is_local_jd:
                    job = _build_local_job(candidate, cfg=ctx.config)
                else:
                    async with semaphore:
                        job = await _enrich_remote_candidate(
                            candidate,
                            scan_meta=scan_meta,
                            client=client,
                            cfg=ctx.config,
                        )
                if not job.description:
                    raise ValueError("description was empty after enrichment")
                return job, None
            except Exception as exc:
                message = f"{candidate.source_ref}: {exc}"
                logger.warning("Career-Ops import skipped %s", message)
                return None, message

        results = await asyncio.gather(*(_enrich_one(candidate) for candidate in candidates))
        for job, error in results:
            if job is not None:
                enriched.append(job)
            if error is not None:
                errors.append(error)

    return enriched, errors


async def _upsert_jobs_raw(
    db: AsyncSession,
    jobs: list[EnrichedCareerOpsJob],
) -> tuple[list[JobRaw], int, int]:
    if not jobs:
        return [], 0, 0

    urls = [job.job_url for job in jobs]
    existing_rows = await db.execute(select(JobRaw.job_url).where(JobRaw.job_url.in_(urls)))
    existing_urls = {row[0] for row in existing_rows.all()}

    values = [
        {
            "job_url": job.job_url,
            "title": _truncate(job.title, _MAX_TITLE_LENGTH),
            "company": _truncate(job.company, _MAX_COMPANY_LENGTH),
            "description": job.description,
            "location": _truncate(job.location, _MAX_LOCATION_LENGTH),
            "site": _truncate(job.site, _MAX_SITE_LENGTH),
            "date_posted": job.date_posted,
            "role_clusters": job.role_clusters,
            "job_profile": job.job_profile,
        }
        for job in jobs
    ]

    insert_stmt = pg_insert(JobRaw).values(values)
    await db.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=["job_url"],
            set_={
                "title": insert_stmt.excluded.title,
                "company": insert_stmt.excluded.company,
                "description": insert_stmt.excluded.description,
                "location": insert_stmt.excluded.location,
                "site": insert_stmt.excluded.site,
                "date_posted": insert_stmt.excluded.date_posted,
                "role_clusters": insert_stmt.excluded.role_clusters,
                "job_profile": insert_stmt.excluded.job_profile,
            },
        )
    )
    await db.flush()
    db.expire_all()

    resolved_rows = await db.execute(
        select(JobRaw)
        .where(JobRaw.job_url.in_(urls))
        .execution_options(populate_existing=True)
    )
    resolved = list(resolved_rows.scalars().all())
    inserted = len([url for url in urls if url not in existing_urls])
    updated = len(urls) - inserted
    return resolved, inserted, updated


async def _embed_jobs(
    db: AsyncSession,
    *,
    jobs: list[JobRaw],
    config_overrides: dict | None = None,
) -> None:
    if not jobs:
        return

    ctx = build_context("__career_ops_import__", "", config_overrides)
    cache = PgEmbeddingCache(db, ctx.config_fp)
    canon = SkillCanonicalizer(ctx.config)
    missing_jobs = [job for job in jobs if job.embedding is None and job.description]
    if not missing_jobs:
        return

    descriptions = [job.description or "" for job in missing_jobs]
    raw_skills_list = extract_skills_from_texts(descriptions, ctx.config)
    text_specs: list[tuple[str, str, str]] = []
    for job, raw_skills in zip(missing_jobs, raw_skills_list):
        canonical_skills = sorted(canon.canonicalize(raw_skills))
        text = build_job_embedding_text(
            title=job.title or "",
            description=job.description or "",
            canonical_skills=canonical_skills,
            cfg=ctx.config,
        )
        text_specs.append((job.job_url, fingerprint_text(text), text))

    cached_vectors = await cache.fetch([spec[1] for spec in text_specs])
    job_rows: list[tuple[str, list[float]]] = []
    missing_specs: list[tuple[str, str, str]] = []

    for job_url, text_fp, text in text_specs:
        vector = cached_vectors.get(text_fp)
        if vector is None:
            missing_specs.append((job_url, text_fp, text))
        else:
            job_rows.append((job_url, list(vector)))

    if missing_specs:
        engine = EmbeddingEngine(ctx.config)
        vectors = engine.embed([spec[2] for spec in missing_specs])
        cache_rows: list[tuple[str, list[float]]] = []
        for (job_url, text_fp, _), vector in zip(missing_specs, vectors):
            clean = vector.tolist()
            cache_rows.append((text_fp, clean))
            job_rows.append((job_url, clean))
        await cache.store_vectors(cache_rows)

    if job_rows:
        await store_job_embeddings(db, job_rows)
    await db.commit()


async def import_career_ops_workspace(
    db: AsyncSession,
    *,
    workspace_path: str | Path,
    user_email: str,
    pending_only: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> CareerOpsImportSummary:
    workspace = Path(workspace_path)
    user_row = await db.execute(
        select(User, Profile)
        .join(Profile, Profile.user_id == User.id)
        .where(User.email == user_email)
    )
    resolved = user_row.first()
    if not resolved:
        raise ValueError(f"User/profile not found for {user_email}")

    user, profile = resolved
    user_id = user.id
    profile_resume_text = profile.resume_text or ""
    profile_distilled_text = profile.distilled_text
    profile_config_overrides = profile.config_overrides or {}
    candidates = parse_career_ops_pipeline(workspace, pending_only=pending_only)
    if limit is not None:
        candidates = candidates[:limit]

    enriched_jobs, errors = await enrich_career_ops_candidates(
        candidates,
        workspace_path=workspace,
        config_overrides=profile_config_overrides,
    )

    if dry_run:
        return CareerOpsImportSummary(
            workspace_path=str(workspace),
            user_email=user_email,
            candidate_count=len(candidates),
            imported_count=len(enriched_jobs),
            inserted_count=0,
            updated_count=0,
            scored_count=0,
            skipped_count=len(candidates) - len(enriched_jobs),
            run_id=None,
            imported_job_urls=[job.job_url for job in enriched_jobs],
            errors=errors,
        )

    persisted_jobs, inserted_count, updated_count = await _upsert_jobs_raw(db, enriched_jobs)
    await _embed_jobs(
        db,
        jobs=persisted_jobs,
        config_overrides=profile_config_overrides,
    )

    run = Run(
        user_id=user_id,
        status="ranking",
        mode="quick",
        trigger_source="career_ops_import",
        executor_type="local",
        progress={
            "corpus_source": "career_ops_import",
            "import_workspace_path": str(workspace),
            "import_candidate_count": len(candidates),
            "import_inserted_count": inserted_count,
            "import_updated_count": updated_count,
            "import_scored_count": 0,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    imported_urls = [job.job_url for job in enriched_jobs]
    ranked_df = await score_jobs_for_user(
        db=db,
        user_id=user_id,
        resume_text=profile_resume_text,
        distilled_text=profile_distilled_text,
        config_overrides=profile_config_overrides,
        job_urls=imported_urls,
        preserve_corpus=True,
    )
    await persist_ranked_results(db, ranked_df=ranked_df, run_id=run.id, user_id=user_id)

    run.status = "success"
    run.finished_at = datetime.now(timezone.utc)
    run.scrape_count = len(enriched_jobs)
    run.job_count = int(len(ranked_df.index))
    run.progress = {
        **(run.progress or {}),
        "import_scored_count": int(len(ranked_df.index)),
        "corpus_job_count": len(imported_urls),
        "scored_job_count": int(len(ranked_df.index)),
        "shown_job_count": int(len(ranked_df.index)),
    }
    await db.commit()

    return CareerOpsImportSummary(
        workspace_path=str(workspace),
        user_email=user_email,
        candidate_count=len(candidates),
        imported_count=len(enriched_jobs),
        inserted_count=inserted_count,
        updated_count=updated_count,
        scored_count=int(len(ranked_df.index)),
        skipped_count=len(candidates) - len(enriched_jobs),
        run_id=run.id,
        imported_job_urls=imported_urls,
        errors=errors,
    )
