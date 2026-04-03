import asyncio
import gc
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, Profile
from api.config import settings
from batch.context import build_context, get_batch, load_base_config
from batch.embedding_cache import PgEmbeddingCache, clear_vector_cache, store_job_embeddings
from batch.memory import log_rss, release_memory
from domain.candidate_profile import build_candidate_profile
from domain.additive_scoring import (
    detect_contract_type,
    recency_score_0_100,
)
from domain.company import CompanyScorer
from domain.description_quality import description_quality_multiplier
from domain.embed_math import cosine_similarity
from domain.embeddings import (
    EmbeddingEngine,
    build_job_embedding_text,
    build_resume_embedding_text,
    fingerprint_text,
    unload_embedding_engine,
)
from domain.job_profile import build_job_profile
from domain.match_judge import judge_match_report
from domain.match_verifier import verify_match_report
from domain.profile_rules import enrich_config_with_profile_rules, title_rule_flags
from domain.profile_rules import profile_description_alignment_multiplier, text_matches_profile_positive_terms
from domain.score_synthesis import synthesize_match_score
from domain.title_relevance import compute_title_relevance, title_relevance_score_0_100
from domain.roles import (
    classify_functional_role,
    consulting_dampener,
    requires_high_semantic_floor,
)
from domain.scoring import (
    calculate_role_and_skill_match_score,
    calculate_seniority_score,
    extract_required_yoe,
    location_tier,
    location_weight,
    recency_weight,
)
from domain.skill_boost import bounded_skill_boost
from domain.skills import SkillCanonicalizer, extract_skills_from_texts
from llm.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)



_JOB_WINDOW_DAYS = load_base_config().get("batch", {}).get("job_window_days", 15)
_RANK_MAX_CANDIDATES = settings.ranker_max_candidates
_RANK_DESCRIPTION_CHARS = settings.ranker_max_description_chars
_RANK_LOAD_CHUNK = load_base_config().get("batch", {}).get("rank_load_chunk", 500)


def _is_uuid_like(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def matches_requested_clusters_for_row(
    requested_clusters: set[str] | None,
    raw_clusters,
    title: str | None,
    description: str | None,
) -> bool:
    from domain.role_clusters import infer_clusters_from_job_text

    if not requested_clusters or "general" in requested_clusters:
        return True
    inferred_clusters = infer_clusters_from_job_text(title, description)
    if inferred_clusters.intersection(requested_clusters):
        return True

    # Stored clusters are a fallback for sparse records where the ranking-time
    # title/description window may not contain enough role evidence.
    text = f"{title or ''} {description or ''}".strip()
    if (
        inferred_clusters == {"general"}
        and len(text) < 120
        and isinstance(raw_clusters, list)
        and raw_clusters
        and set(raw_clusters).issubset(requested_clusters | {"general"})
    ):
        return bool(set(raw_clusters).intersection(requested_clusters))
    return False


async def load_jobs_dataframe(
    db: AsyncSession,
    role_clusters: set[str] | None = None,
    *,
    job_urls: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    _cols = (
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, _RANK_DESCRIPTION_CHARS).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted, JobRaw.role_clusters, JobRaw.embedding,
    )

    if job_urls:
        logger.info("Loading jobs from filtered set of %d URLs (offset=%d)", len(job_urls), offset)
        stmt = (
            select(*_cols)
            .where(JobRaw.ingested_at >= cutoff)
            .where(JobRaw.job_url.in_(job_urls))
            .order_by(JobRaw.ingested_at.desc(), JobRaw.id.desc())
        )
    else:
        # DISTINCT ON (company, title, location) deduplicates cross-source
        # reposts at the SQL level — cuts ~42% of rows before they hit pandas.
        # Keeps the row with the longest description per group.
        _co = func.lower(func.trim(JobRaw.company))
        _ti = func.lower(func.trim(JobRaw.title))
        _lo = func.lower(func.trim(JobRaw.location))
        stmt = (
            select(*_cols)
            .distinct(_co, _ti, _lo)
            .where(JobRaw.ingested_at >= cutoff)
            .order_by(
                _co, _ti, _lo,
                func.length(JobRaw.description).desc().nulls_last(),
                JobRaw.ingested_at.desc(),
            )
        )
        logger.debug("Loading jobs from global pool with SQL dedup (offset=%d)", offset)

    stmt = stmt.offset(offset).limit(limit or _RANK_MAX_CANDIDATES)

    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return pd.DataFrame(
            columns=["id", "job_url", "title", "company", "description",
                     "location", "site", "date_posted", "role_clusters", "embedding"]
        )
    df = pd.DataFrame(
        rows,
        columns=["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted", "role_clusters", "embedding"],
    )
    if role_clusters and "general" not in role_clusters:
        match_mask = df.apply(
            lambda r: matches_requested_clusters_for_row(
                role_clusters,
                r["role_clusters"],
                r["title"],
                r["description"],
            ),
            axis=1,
        )
        df = df.loc[match_mask].reset_index(drop=True)
    return df


async def load_jobs_by_ids_dataframe(
    db: AsyncSession,
    job_ids: list[str],
) -> pd.DataFrame:
    if not job_ids:
        return pd.DataFrame(
            columns=["id", "job_url", "title", "company", "description",
                     "location", "site", "date_posted", "role_clusters", "embedding"]
        )
    stmt = select(
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, _RANK_DESCRIPTION_CHARS).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted, JobRaw.role_clusters, JobRaw.job_profile, JobRaw.embedding,
    ).where(JobRaw.id.in_(job_ids))
    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return pd.DataFrame(
            columns=["id", "job_url", "title", "company", "description",
                     "location", "site", "date_posted", "role_clusters", "job_profile", "embedding"]
        )
    return pd.DataFrame(
        rows,
        columns=["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted", "role_clusters", "job_profile", "embedding"],
    )


_ANN_PREFILTER_CANDIDATES = 600


async def ann_prefilter_job_urls(
    db: AsyncSession,
    resume_embedding: list[float],
    *,
    limit: int = _ANN_PREFILTER_CANDIDATES,
    cutoff: datetime | None = None,
) -> list[str]:
    """Return top-N job URLs by cosine similarity to the resume embedding.

    Uses the HNSW index on jobs_raw.embedding for sub-millisecond ANN lookup.
    Only considers jobs with a stored embedding; jobs without embeddings are
    handled by the fallback path in the caller.
    """
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    rows = await db.execute(
        text("""
            SELECT job_url FROM jobs_raw
            WHERE embedding IS NOT NULL
              AND ingested_at >= :cutoff
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """),
        {"vec": str(resume_embedding), "cutoff": cutoff, "limit": limit},
    )
    return [r[0] for r in rows.all()]


def _apply_pre_filters(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    blocklist = cfg.get("title_blocklist", [])
    if blocklist:
        rx = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, blocklist)), re.I)
        mask &= ~df["title"].fillna("").astype(str).str.contains(rx)
    max_yoe = cfg.get("experience", {}).get("max_yoe")
    if max_yoe is not None:
        required_yoe = df["description"].apply(extract_required_yoe)
        mask &= required_yoe.isna() | (required_yoe <= max_yoe)
    return df.loc[mask].reset_index(drop=True)


def _dedupe_before_embedding(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    dedupe_key = (
        df["title"].fillna("").astype(str).str.strip().str.lower()
        + "|"
        + df["company"].fillna("").astype(str).str.strip().str.lower()
        + "|"
        + df["location"].fillna("").astype(str).str.strip().str.lower()
    )
    working = df.assign(
        _pre_embed_key=dedupe_key,
        _desc_len=df["description"].fillna("").astype(str).str.len(),
    )
    working = (
        working.sort_values(["_pre_embed_key", "_desc_len"], ascending=[True, False])
        .drop_duplicates(subset="_pre_embed_key", keep="first")
        .drop(columns=["_pre_embed_key", "_desc_len"])
        .reset_index(drop=True)
    )
    return working


def _apply_semantic_gates(df: pd.DataFrame, cfg: dict, role_intent: str) -> pd.DataFrame:
    mask_non_ic = df["title"].astype(str).apply(requires_high_semantic_floor)
    mask_semantic = df["semantic_score"] >= 0.75
    mask = ~mask_non_ic | mask_semantic

    desc_quality = df["description"].apply(description_quality_multiplier)
    ranking = cfg.get("ranking", {})
    min_q = ranking.get("min_quality_multiplier", 0.0)
    mask &= desc_quality >= min_q

    thresholds = ranking.get("role_semantic_thresholds", {})
    min_sem = thresholds.get(role_intent, ranking.get("min_semantic_score", 0.20))
    mask &= df["semantic_score"] >= min_sem

    title_rule_cfg = ranking.get("profile_title_rule_scoring", {})
    strong_cfg = title_rule_cfg.get("strong", {})
    adjacent_cfg = title_rule_cfg.get("adjacent", {})
    hybrid_cfg = title_rule_cfg.get("hybrid", {})

    if "strong_title_penalty" in df:
        strong_mask = df["strong_title_penalty"].fillna(False)
        mask &= ~(
            strong_mask
            & (df["semantic_score"] < strong_cfg.get("semantic_floor", 0.56))
            & (df["skill_overlap"] < strong_cfg.get("min_skill_overlap", 2))
        )
    if "adjacent_title" in df:
        adjacent_mask = df["adjacent_title"].fillna(False) & ~df["strong_title_penalty"].fillna(False)
        mask &= ~(
            adjacent_mask
            & (df["semantic_score"] < adjacent_cfg.get("semantic_floor", 0.50))
            & (df["skill_overlap"] < adjacent_cfg.get("min_skill_overlap", 2))
        )
    if "hybrid_title" in df:
        hybrid_mask = df["hybrid_title"].fillna(False) & ~df["strong_title_penalty"].fillna(False)
        mask &= ~(
            hybrid_mask
            & (df["semantic_score"] < hybrid_cfg.get("semantic_floor", 0.52))
            & (df["skill_overlap"] < hybrid_cfg.get("min_skill_overlap", 3))
        )

    positive_terms = (cfg.get("ranking", {}) or {}).get("profile_positive_terms", {})
    if positive_terms:
        positive_mask = df.apply(
            lambda r: text_matches_profile_positive_terms(
                f"{r['title'] or ''} {r['description'] or ''}",
                cfg,
            ),
            axis=1,
        )
        mask &= positive_mask

    title_relevance_floor = ranking.get("title_relevance_floor", 0.0)
    if title_relevance_floor > 0 and "title_relevance" in df:
        mask &= df["title_relevance"] >= title_relevance_floor

    out = df.loc[mask].reset_index(drop=True)
    out["description_quality"] = desc_quality.loc[mask].values
    return out


def _apply_additive_scoring(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    ranking_cfg = cfg.get("ranking", {})

    # Skills score — vectorized
    damp = df["title"].apply(consulting_dampener)
    base = df["semantic_score"] * 100
    base = base + np.minimum(df["skill_overlap"] * 2, 8)
    role_mod = np.clip((df["role_skill_score"] - 1.0) * 25, -10, 10)
    base = base + role_mod
    func_mod = np.clip((df["functional_role_penalty"] - 1.0) * 50, -8, 10)
    base = base + func_mod
    base = base - (damp < 1.0).astype(float) * 10
    
    # Apply skill coverage penalty
    from domain.additive_scoring import skill_coverage_penalty as _coverage_penalty
    if "skill_coverage" in df.columns:
        coverage_penalties = df["skill_coverage"].apply(_coverage_penalty)
        base = base + coverage_penalties
    
    df["skills_score"] = np.clip(base, 0, 100)

    # Company score — vectorized
    _TIER_SCORE_MAP = {
        "tier_ss": 100.0, "tier_s": 95.0, "tier_a": 85.0, "tier_b": 65.0,
        "tier_c": 45.0, "tier_d": 15.0, "preferred": 100.0, "deprioritized": 15.0,
    }
    df["company_score"] = df["company_tier"].map(_TIER_SCORE_MAP).fillna(40.0)

    semantic_floor = cfg.get("ranking", {}).get("company_semantic_floor", 0.60)
    if semantic_floor > 0:
        below_floor = df["semantic_score"] < semantic_floor
        df.loc[below_floor, "company_score"] *= df.loc[below_floor, "semantic_score"] / semantic_floor

    gem_threshold = cfg.get("ranking", {}).get("hidden_gem_semantic_threshold", 0.70)
    gem_bonus = cfg.get("ranking", {}).get("hidden_gem_company_bonus", 60)
    is_default_tier = df["company_tier"].isin(["default", "", None]) | df["company_tier"].isna()
    high_semantic = df["semantic_score"] >= gem_threshold
    gem_mask = is_default_tier & high_semantic
    df.loc[gem_mask, "company_score"] = np.maximum(df.loc[gem_mask, "company_score"], gem_bonus)

    # Company score relevance dampening: high-tier company for irrelevant role still gets penalized
    company_tr_floor = ranking_cfg.get("company_title_relevance_floor", 0.0)
    if company_tr_floor > 0 and "title_relevance" in df:
        relevance_factor = np.clip(df["title_relevance"] / company_tr_floor, 0.3, 1.0)
        df["company_score"] = df["company_score"] * relevance_factor

    # Seniority — vectorized
    df["seniority_score_dim"] = np.clip(((df["seniority_score"] - 0.4) / 0.75) * 90 + 10, 0, 100)

    # Location — vectorized
    if "location_score" not in df.columns:
        df["location_score"] = 40.0

    # Recency — still per-row (date parsing)
    df["recency_score"] = df["date_posted"].apply(recency_score_0_100)

    # Title-role relevance score (0-100)
    if "title_relevance" in df:
        tr_low = ranking_cfg.get("title_relevance_low", 0.25)
        tr_high = ranking_cfg.get("title_relevance_high", 0.90)
        df["title_relevance_score"] = title_relevance_score_0_100(
            df["title_relevance"].values, low=tr_low, high=tr_high
        )
    else:
        df["title_relevance_score"] = 100.0

    # Weighted final score — vectorized.
    # title_relevance is removed from additive weights; its 0.10 share is
    # redistributed to skills (+0.05) and recency (+0.05). It is applied
    # instead as a post-multiplier so off-domain titles are penalised
    # proportionally rather than just losing a fixed additive bonus.
    w = ranking_cfg.get("scoring_weights", {})
    df["final_score"] = (
        df["skills_score"] * w.get("skills_match", 0.40)
        + df["company_score"] * w.get("company_fit", 0.15)
        + df["seniority_score_dim"] * w.get("seniority", 0.15)
        + df["location_score"] * w.get("location", 0.15)
        + df["recency_score"] * w.get("recency", 0.15)
    ).fillna(0.0)

    # Title-relevance multiplier: maps tr_score [0, 100] → multiplier [0.70, 1.0].
    # A perfectly irrelevant title (tr=0) gets a 30% penalty; perfectly relevant
    # (tr=100) passes through unchanged. Override via ranking.title_relevance_multiplier_min.
    tr_min = ranking_cfg.get("title_relevance_multiplier_min", 0.70)
    tr_multiplier = np.clip(
        tr_min + (1.0 - tr_min) * (df["title_relevance_score"] / 100.0),
        tr_min, 1.0,
    )
    df["final_score"] = df["final_score"] * tr_multiplier

    title_rule_cfg = cfg.get("ranking", {}).get("profile_title_rule_scoring", {})
    strong_cfg = title_rule_cfg.get("strong", {})
    adjacent_cfg = title_rule_cfg.get("adjacent", {})
    hybrid_cfg = title_rule_cfg.get("hybrid", {})

    if "strong_title_penalty" in df:
        df.loc[df["strong_title_penalty"], "final_score"] *= strong_cfg.get("multiplier", 0.72)

    if "adjacent_title" in df:
        adjacent_mask = df["adjacent_title"] & ~df["strong_title_penalty"]
        adjacent_keep = (
            (df["semantic_score"] >= adjacent_cfg.get("keep_semantic_floor", 0.58))
            & (df["role_skill_score"] >= adjacent_cfg.get("keep_role_skill_score", 1.12))
        )
        df.loc[adjacent_mask & ~adjacent_keep, "final_score"] *= adjacent_cfg.get("multiplier", 0.88)

    if "hybrid_title" in df:
        hybrid_mask = df["hybrid_title"] & ~df["strong_title_penalty"]
        hybrid_keep = (
            (df["semantic_score"] >= hybrid_cfg.get("keep_semantic_floor", 0.60))
            & (df["role_skill_score"] >= hybrid_cfg.get("keep_role_skill_score", 1.15))
        )
        df.loc[hybrid_mask & ~hybrid_keep, "final_score"] *= hybrid_cfg.get("multiplier", 0.82)

    df["profile_alignment_multiplier"] = df.apply(
        lambda r: profile_description_alignment_multiplier(
            r.get("title") or "",
            r.get("description") or "",
            cfg,
        ),
        axis=1,
    )
    df["final_score"] = df["final_score"] * df["profile_alignment_multiplier"]

    # Contract penalty — vectorized
    contract_penalty = cfg.get("ranking", {}).get("contract_penalty", 0.9)
    df["is_contract"] = df.apply(
        lambda r: detect_contract_type(r["title"], r["description"]), axis=1,
    )
    df.loc[df["is_contract"], "final_score"] *= contract_penalty
    return df


def _agentic_client_or_none() -> OpenRouterClient | None:
    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        return None
    try:
        return OpenRouterClient(api_key=api_key)
    except Exception:
        logger.warning("Agentic matching disabled: could not initialize OpenRouter client", exc_info=True)
        return None


def _row_job_profile(row: pd.Series, cfg: dict, persisted_job_profile: dict | None = None) -> dict:
    job_profile = persisted_job_profile or row.get("job_profile")
    if isinstance(job_profile, dict) and job_profile:
        return job_profile
    return build_job_profile(
        title=row.get("title"),
        company=row.get("company"),
        description=row.get("description"),
        location=row.get("location"),
        site=row.get("site"),
        date_posted=row.get("date_posted"),
        role_clusters=row.get("role_clusters"),
        cfg=cfg,
    )


def _row_match_payload(row: pd.Series) -> str:
    description = str(row.get("description") or "")
    return "\n".join(
        part
        for part in [
            f"TITLE: {row.get('title') or ''}",
            f"COMPANY: {row.get('company') or ''}",
            f"LOCATION: {row.get('location') or ''}",
            description[:2000],
        ]
        if part
    )


async def _judge_selected_jobs(
    df: pd.DataFrame,
    *,
    selected_indices: list[int],
    candidate_profile: dict,
    resume_text: str,
    cfg: dict,
    llm_client: OpenRouterClient | None,
    persisted_job_profiles: dict[str, dict] | None = None,
) -> list[dict]:
    tasks = []
    for idx in selected_indices:
        row = df.loc[idx]
        job_profile = _row_job_profile(row, cfg, (persisted_job_profiles or {}).get(str(row["id"])))
        job_text = _row_match_payload(row)
        tasks.append(
            judge_match_report(
                candidate_profile=candidate_profile,
                job_profile=job_profile,
                resume_text=resume_text,
                job_text=job_text,
                llm_client=llm_client,
                max_tokens=cfg.get("ranking", {}).get("agentic_matching", {}).get("max_judge_tokens", 1200),
            )
        )
    return await asyncio.gather(*tasks)


async def _verify_selected_jobs(
    match_reports: list[dict],
    selected_rows: list[pd.Series],
    *,
    candidate_profile: dict,
    cfg: dict,
    llm_client: OpenRouterClient | None,
    persisted_job_profiles: dict[str, dict] | None = None,
) -> list[dict]:
    tasks = []
    for match_report, row in zip(match_reports, selected_rows):
        job_profile = _row_job_profile(row, cfg, (persisted_job_profiles or {}).get(str(row["id"])))
        tasks.append(
            verify_match_report(
                match_report=match_report,
                candidate_profile=candidate_profile,
                job_profile=job_profile,
                llm_client=llm_client,
                max_tokens=cfg.get("ranking", {}).get("agentic_matching", {}).get("max_verifier_tokens", 700),
            )
        )
    return await asyncio.gather(*tasks)


async def _apply_agentic_matching(
    df: pd.DataFrame,
    *,
    cfg: dict,
    user_id: str,
    resume_text: str,
    profile: Profile | None,
    db: AsyncSession,
    llm_client: OpenRouterClient | None = None,
) -> pd.DataFrame:
    agentic_cfg = cfg.get("ranking", {}).get("agentic_matching", {}) or {}
    if not agentic_cfg.get("enabled", False) or df.empty:
        df["match_report"] = None
        df["verification_report"] = None
        df["fit_band"] = None
        df["confidence_band"] = None
        df["explanation_summary"] = None
        return df

    for column in ("match_report", "verification_report", "fit_band", "confidence_band", "explanation_summary"):
        if column not in df.columns:
            df[column] = None

    candidate_profile = None
    if profile and isinstance(profile.candidate_profile, dict):
        candidate_profile = profile.candidate_profile
    else:
        candidate_profile = build_candidate_profile(profile=profile, resume_text=resume_text, cfg=cfg)

    created_client = False
    if llm_client is None:
        llm_client = _agentic_client_or_none()
        created_client = llm_client is not None

    try:
        judge_top_n = int(agentic_cfg.get("judge_top_n", 20))
        min_score = float(agentic_cfg.get("min_deterministic_score", 45))
        eligible = df[df["final_score"] >= min_score].nlargest(judge_top_n, "final_score")
        if eligible.empty:
            df["match_report"] = None
            df["verification_report"] = None
            df["fit_band"] = None
            df["confidence_band"] = None
            df["explanation_summary"] = None
            return df

        selected_indices = list(eligible.index)
        selected_rows = [df.loc[idx] for idx in selected_indices]
        selected_job_ids = [str(df.at[idx, "id"]) for idx in selected_indices]
        persisted_job_profiles: dict[str, dict] = {}
        if selected_job_ids:
            profile_rows = await db.execute(
                select(JobRaw.id, JobRaw.job_profile).where(JobRaw.id.in_(selected_job_ids))
            )
            for job_id, job_profile in profile_rows.all():
                if isinstance(job_profile, dict) and job_profile:
                    persisted_job_profiles[str(job_id)] = job_profile
        match_reports = await _judge_selected_jobs(
            df,
            selected_indices=selected_indices,
            candidate_profile=candidate_profile,
            resume_text=resume_text,
            cfg=cfg,
            llm_client=llm_client,
            persisted_job_profiles=persisted_job_profiles,
        )
        verification_reports = await _verify_selected_jobs(
            match_reports,
            selected_rows,
            candidate_profile=candidate_profile,
            cfg=cfg,
            llm_client=llm_client,
            persisted_job_profiles=persisted_job_profiles,
        )

        for idx, row, match_report, verification_report in zip(selected_indices, selected_rows, match_reports, verification_reports):
            synthesis = synthesize_match_score(
                deterministic_score=float(row["final_score"] or 0.0),
                match_report=match_report,
                verification_report=verification_report,
            )
            df.at[idx, "final_score"] = synthesis["final_score"]
            df.at[idx, "fit_band"] = synthesis["fit_band"]
            df.at[idx, "confidence_band"] = synthesis["confidence_band"]
            df.at[idx, "explanation_summary"] = synthesis["explanation_summary"]
            df.at[idx, "match_report"] = match_report
            df.at[idx, "verification_report"] = verification_report

        return df
    finally:
        if created_client and llm_client is not None:
            try:
                await llm_client.close()
            except Exception:
                logger.debug("Agentic LLM client close skipped", exc_info=True)


_SENIORITY_SUFFIXES = re.compile(
    r"\s*[-\u2013\u2014]\s*(?:vice president|assistant vice president|"
    r"senior vice president|vp|avp|svp|associate|"
    r"senior associate|principal associate)\s*$",
    re.I,
)


async def _compute_embeddings(
    df: pd.DataFrame,
    cfg: dict,
    db: AsyncSession,
    cfg_fp: str,
    user_id: str,
    resume_text: str,
    persisted_resume_embedding: list[float] | None = None,
    distilled_text: str | None = None,
    *,
    canon: SkillCanonicalizer | None = None,
    base_cfg_fp: str | None = None,
) -> pd.DataFrame:
    t_emb = time.monotonic()

    # Pop the embedding column immediately and convert each Python list → float32 ndarray.
    # This frees ~7.7KB of Python object overhead per row (384 floats × 24 bytes) before
    # any subsequent DataFrame operations, reducing peak RSS by ~3.8MB per 500-row chunk.
    emb_series = df.pop("embedding")
    stored_embeddings = [
        np.array(e, dtype="float32") if e is not None else None
        for e in emb_series
    ]
    del emb_series

    if base_cfg_fp is None:
        base_cfg_fp = build_context(user_id="__base__", resume_text="").config_fp
    job_cache = PgEmbeddingCache(db, base_cfg_fp)
    resume_cache = PgEmbeddingCache(db, cfg_fp)

    raw_skills = extract_skills_from_texts(df["description"].fillna("").tolist(), cfg)
    if canon is None:
        canon = SkillCanonicalizer(cfg)
    df["canonical_skills"] = [sorted(canon.canonicalize(s)) for s in raw_skills]
    df["skill_overlap"] = df["canonical_skills"].apply(len)

    # Extract user's canonical skills from resume for coverage calculation.
    # Run once per ranking call (not per job).
    if resume_text or distilled_text:
        _resume_for_skills = distilled_text or resume_text or ""
        _user_raw_skills = extract_skills_from_texts([_resume_for_skills], cfg)
        _user_canonical = set(canon.canonicalize(_user_raw_skills[0])) if _user_raw_skills else set()
    else:
        _user_canonical = set()

    def _coverage(job_skills: list[str]) -> float:
        if not job_skills:
            return 0.0
        matched = len(set(job_skills) & _user_canonical)
        return matched / len(job_skills)

    df["matched_skills"] = df["canonical_skills"].apply(lambda s: len(set(s) & _user_canonical))
    df["skill_coverage"] = df["canonical_skills"].apply(_coverage)

    dim = cfg["embeddings"]["embedding_dim"]
    vectors = np.zeros((len(df), dim), dtype="float32")
    stored_hits = 0
    miss_specs: list[tuple[int, str, str]] = []
    for i, (t, d, cs, stored_embedding) in enumerate(
        zip(df["title"], df["description"], df["canonical_skills"], stored_embeddings)
    ):
        if stored_embedding is not None:
            vectors[i] = stored_embedding
            stored_hits += 1
            continue
        job_text = build_job_embedding_text(title=t, description=d, canonical_skills=cs, cfg=cfg)
        miss_specs.append((i, fingerprint_text(job_text), job_text))
    del stored_embeddings

    cached = await job_cache.fetch([text_fp for _, text_fp, _ in miss_specs])
    misses: list[tuple[int, str]] = []
    miss_text_by_row_idx: dict[int, str] = {}
    cached_job_rows: list[tuple[str, list[float]]] = []
    for row_idx, text_fp, job_text in miss_specs:
        if text_fp in cached:
            vectors[row_idx] = np.array(cached[text_fp], dtype="float32")
            cached_job_rows.append((df.at[row_idx, "job_url"], cached[text_fp]))
        else:
            misses.append((row_idx, text_fp))
            miss_text_by_row_idx[row_idx] = job_text

    logger.info(
        "Embedding cache: %d stored hits, %d cache hits, %d misses out of %d jobs",
        stored_hits, len(cached), len(misses), len(df),
    )
    log_rss(logger, "rank_embed_prepare", jobs=len(df), cache_misses=len(misses))

    engine = None
    if misses:
        engine = EmbeddingEngine(cfg)
        total = len(misses)
        rank_embed_chunk = get_batch(cfg, "rank_embed_chunk", 4)
        if cached_job_rows:
            await store_job_embeddings(db, cached_job_rows)
            await db.commit()
            cached_job_rows.clear()
        for chunk_start in range(0, total, rank_embed_chunk):
            chunk_end = min(chunk_start + rank_embed_chunk, total)
            chunk = misses[chunk_start:chunk_end]
            chunk_texts = [miss_text_by_row_idx[row_idx] for row_idx, _ in chunk]

            new_vecs = await asyncio.to_thread(engine.embed, chunk_texts)
            cache_rows: list[tuple[str, list[float]]] = []
            job_embedding_rows: list[tuple[str, list[float]]] = []

            for (row_idx, text_fp), v in zip(chunk, new_vecs):
                vector = v.tolist()
                cache_rows.append((text_fp, vector))
                job_embedding_rows.append((df.at[row_idx, "job_url"], vector))
                vectors[row_idx] = v

            await job_cache.store_vectors(cache_rows)
            await store_job_embeddings(db, job_embedding_rows)
            await db.commit()

            logger.info("Ranking embed: %d/%d", chunk_end, total)
            log_rss(logger, "rank_embed_progress", encoded=chunk_end, total=total)

    elif cached_job_rows:
        await store_job_embeddings(db, cached_job_rows)
        await db.commit()

    resume_emb_text = build_resume_embedding_text(
        resume_text=resume_text,
        distilled=distilled_text or cfg.get("resume", {}).get("distilled_text"),
        cfg=cfg,
        use_case="default",
    )
    resume_fp = fingerprint_text(resume_emb_text)
    resume_cached = await resume_cache.fetch([resume_fp])

    if persisted_resume_embedding is not None:
        r_emb = np.array(persisted_resume_embedding, dtype="float32")
    elif resume_fp in resume_cached:
        r_emb = np.array(resume_cached[resume_fp], dtype="float32")
    else:
        if engine is None:
            engine = EmbeddingEngine(cfg)
        r_emb = (await asyncio.to_thread(engine.embed, [resume_emb_text]))[0]
        await resume_cache.store_vectors([(resume_fp, r_emb.tolist())])
        if _is_uuid_like(user_id):
            profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = profile_result.scalar_one_or_none()
            if profile:
                profile.resume_embedding = r_emb.tolist()
            await db.commit()

    df["semantic_score"] = cosine_similarity(r_emb, vectors)
    nan_count = df["semantic_score"].isna().sum()
    if nan_count:
        logger.warning("semantic_score has %d NaN values, filling with 0", nan_count)
        df["semantic_score"] = df["semantic_score"].fillna(0.0)

    # Title-role relevance: embed job titles and compare to target roles
    target_roles = cfg.get("profile_intent", {}).get("roles") or []
    if target_roles:
        if engine is None:
            engine = EmbeddingEngine(cfg)
        title_texts = df["title"].fillna("").astype(str).tolist()
        title_vecs = await asyncio.to_thread(engine.embed, title_texts)
        role_vecs = await asyncio.to_thread(engine.embed, target_roles)
        df["title_relevance"] = compute_title_relevance(
            title_vecs.tolist(), role_vecs
        )
        logger.info(
            "Title relevance computed for %d jobs against %d target roles",
            len(df), len(target_roles),
        )
    else:
        df["title_relevance"] = 1.0

    logger.info(
        "Embeddings computed",
        extra={"jobs": len(df), "cache_misses": len(misses),
               "duration_s": round(time.monotonic() - t_emb, 2)},
    )
    log_rss(logger, "rank_embed_done", jobs=len(df), cache_misses=len(misses))
    df = df.drop(columns=["canonical_skills"], errors="ignore")
    del vectors, cached, raw_skills, canon
    del miss_specs, miss_text_by_row_idx
    if "new_vecs" in locals():
        del new_vecs
    if "r_emb" in locals():
        del r_emb
    release_memory(logger, "rank_embed_release", jobs=len(df), cache_misses=len(misses))
    return df


async def score_jobs_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
    job_urls: list[str] | None = None,
) -> pd.DataFrame:
    from domain.role_clusters import roles_to_clusters

    llm_client = None
    try:
        if job_urls:
            logger.info("Ranking against %d freshly scraped jobs (filtered mode)", len(job_urls))
        ctx = build_context(user_id, resume_text, config_overrides)
        profile_roles = ctx.config.get("profile_intent", {}).get("roles", [])
        clusters = roles_to_clusters(profile_roles) if profile_roles else None
        cfg = enrich_config_with_profile_rules(
            ctx.config,
            resume_text=resume_text,
            profile_roles=profile_roles,
        )
        logger.info(
            "Profile title rules",
            extra={
                "user_id": user_id,
                "archetypes": cfg.get("ranking", {}).get("profile_archetypes", []),
                "rule_counts": {
                    name: len(patterns)
                    for name, patterns in (cfg.get("ranking", {}).get("profile_title_rules", {}) or {}).items()
                },
            },
        )
        role_intent = (
            cfg.get("profile_intent", {}).get("preset")
            or cfg.get("ranking", {}).get("default_role")
            or "software_general"
        )

        profile = None
        persisted_resume_embedding = None
        if _is_uuid_like(user_id):
            profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
            profile = profile_result.scalar_one_or_none()
            if profile and profile.resume_embedding is not None:
                persisted_resume_embedding = list(profile.resume_embedding)

        if cfg.get("ranking", {}).get("agentic_matching", {}).get("enabled", False):
            llm_client = _agentic_client_or_none()

        # ANN pre-filter: when no specific job_urls are requested and a resume
        # embedding is available, use the HNSW index to narrow candidates from
        # _RANK_MAX_CANDIDATES (2000) to _ANN_PREFILTER_CANDIDATES (600) before
        # full scoring. Falls back to the global pool if ANN returns too few results.
        effective_job_urls = job_urls
        if effective_job_urls is None and persisted_resume_embedding is not None:
            ann_urls = await ann_prefilter_job_urls(db, persisted_resume_embedding)
            if len(ann_urls) >= 50:
                effective_job_urls = ann_urls
                logger.info("ANN pre-filter: %d candidates (embedding-based)", len(ann_urls))
            else:
                logger.info("ANN pre-filter skipped: only %d embedded jobs, using global pool", len(ann_urls))

        base_cfg_fp = build_context(user_id="__base__", resume_text="").config_fp
        canon = SkillCanonicalizer(cfg)
        frames: list[pd.DataFrame] = []
        total_loaded = 0
        total_scored = 0
        rank_load_chunk = max(1, min(_RANK_LOAD_CHUNK, _RANK_MAX_CANDIDATES))

        for offset in range(0, _RANK_MAX_CANDIDATES, rank_load_chunk):
            page_limit = min(rank_load_chunk, _RANK_MAX_CANDIDATES - offset)
            df = await load_jobs_dataframe(db, role_clusters=clusters, job_urls=effective_job_urls, limit=page_limit, offset=offset)
            if df.empty:
                break
            total_loaded += len(df)
            log_rss(logger, "rank_jobs_loaded_chunk", jobs=len(df), offset=offset, total_loaded=total_loaded)

            scored = await _score_loaded_jobs_dataframe(
                db=db,
                df=df,
                user_id=user_id,
                resume_text=resume_text,
                config_overrides=config_overrides,
                distilled_text=distilled_text,
                cfg=cfg,
                role_intent=role_intent,
                persisted_resume_embedding=persisted_resume_embedding,
                skip_context_enrichment=True,
                canon=canon,
                base_cfg_fp=base_cfg_fp,
                profile=profile,
                llm_client=llm_client,
            )
            if not scored.empty:
                total_scored += len(scored)
                frames.append(scored)
            logger.info(
                "Ranking chunk complete: loaded=%d scored=%d offset=%d/%d",
                len(df),
                len(scored),
                offset + len(df),
                _RANK_MAX_CANDIDATES,
            )
            log_rss(logger, "rank_chunk_done", offset=offset, loaded=len(df), scored=len(scored))
            del df, scored
            release_memory(logger, "rank_chunk_release", offset=offset)

            if len(frames) > 1:
                merged = pd.concat(frames, ignore_index=True)
                merged = merged.sort_values("final_score", ascending=False).head(_RANK_MAX_CANDIDATES).reset_index(drop=True)
                frames = [merged]
                log_rss(logger, "rank_chunk_merge", rows=len(merged))
                release_memory(logger, "rank_chunk_merge_release", rows=len(merged))

            if len(frames) == 1 and len(frames[0]) >= _RANK_MAX_CANDIDATES and offset + len(frames[0]) >= _RANK_MAX_CANDIDATES:
                break

        unload_embedding_engine()
        clear_vector_cache()
        if not frames:
            return pd.DataFrame(columns=["final_score"])

        df = pd.concat(frames, ignore_index=True)
        logger.info("Ranking chunked aggregation complete: loaded=%d scored=%d", total_loaded, len(df))
        log_rss(logger, "rank_jobs_aggregated", total_loaded=total_loaded, scored=len(df))
        return _finalize_ranked_dataframe(df, user_id, role_intent="chunked")
    finally:
        if llm_client is not None:
            await llm_client.close()


async def score_job_ids_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    job_ids: list[str],
    config_overrides: dict | None,
    distilled_text: str | None = None,
) -> pd.DataFrame:
    df = await load_jobs_by_ids_dataframe(db, job_ids)
    profile = None
    if _is_uuid_like(user_id):
        profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
        profile = profile_result.scalar_one_or_none()
    llm_client = _agentic_client_or_none()
    try:
        return await _score_loaded_jobs_dataframe(
            db=db,
            df=df,
            user_id=user_id,
            resume_text=resume_text,
            config_overrides=config_overrides,
            distilled_text=distilled_text,
            profile=profile,
            llm_client=llm_client,
        )
    finally:
        if llm_client is not None:
            await llm_client.close()


async def _score_loaded_jobs_dataframe(
    db: AsyncSession,
    df: pd.DataFrame,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
    *,
    cfg: dict | None = None,
    role_intent: str | None = None,
    persisted_resume_embedding: list[float] | None = None,
    skip_context_enrichment: bool = False,
    canon: SkillCanonicalizer | None = None,
    base_cfg_fp: str | None = None,
    profile: Profile | None = None,
    llm_client: OpenRouterClient | None = None,
) -> pd.DataFrame:
    t_total = time.monotonic()
    ctx = build_context(user_id, resume_text, config_overrides)
    if cfg is None:
        cfg = ctx.config
    if not skip_context_enrichment:
        profile_roles = cfg.get("profile_intent", {}).get("roles", [])
        cfg = enrich_config_with_profile_rules(
            cfg,
            resume_text=resume_text,
            profile_roles=profile_roles,
        )
        logger.info(
            "Profile title rules",
            extra={
                "user_id": user_id,
                "archetypes": cfg.get("ranking", {}).get("profile_archetypes", []),
                "rule_counts": {
                    name: len(patterns)
                    for name, patterns in (cfg.get("ranking", {}).get("profile_title_rules", {}) or {}).items()
                },
            },
        )

    if profile is None and _is_uuid_like(user_id):
        profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
        profile = profile_result.scalar_one_or_none()

    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    df = _apply_pre_filters(df, cfg)
    log_rss(logger, "rank_prefilter_done", jobs=len(df))
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    pre_dedupe_count = len(df)
    df = _dedupe_before_embedding(df)
    if len(df) != pre_dedupe_count:
        logger.info("Pre-embedding dedupe removed %d duplicate rows", pre_dedupe_count - len(df))
    log_rss(logger, "rank_preembed_dedupe_done", jobs=len(df))

    effective_role_intent = role_intent or (
        cfg.get("profile_intent", {}).get("preset")
        or cfg.get("ranking", {}).get("default_role")
        or "software_general"
    )

    effective_persisted_resume_embedding = persisted_resume_embedding
    if effective_persisted_resume_embedding is None and _is_uuid_like(user_id):
        if profile and profile.resume_embedding is not None:
            effective_persisted_resume_embedding = list(profile.resume_embedding)

    df = await _compute_embeddings(
        df,
        cfg,
        db,
        ctx.config_fp,
        user_id,
        resume_text,
        persisted_resume_embedding=effective_persisted_resume_embedding,
        distilled_text=distilled_text,
        canon=canon,
        base_cfg_fp=base_cfg_fp,
    )

    df = _apply_semantic_gates(df, cfg, effective_role_intent)
    log_rss(logger, "rank_semantic_gates_done", jobs=len(df))
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    df["semantic_score"] *= df["skill_overlap"].apply(bounded_skill_boost)
    title_flags = df["title"].fillna("").astype(str).apply(lambda t: title_rule_flags(t, cfg))
    df["strong_title_penalty"] = title_flags.apply(lambda x: x["strong"])
    df["adjacent_title"] = title_flags.apply(lambda x: x["adjacent"])
    df["hybrid_title"] = title_flags.apply(lambda x: x["hybrid"])

    df["functional_role"] = df.apply(
        lambda r: classify_functional_role(r["title"] or "", r["description"] or "", cfg),
        axis=1,
    )
    df["role_skill_score"] = df.apply(
        lambda r: calculate_role_and_skill_match_score(
            cfg, title=r["title"], description=r["description"],
        ),
        axis=1,
    )
    scorer = CompanyScorer(cfg)
    df["company_weight"] = df["company"].apply(scorer.score)
    df["company_tier"] = df["company"].apply(scorer.classify)
    df["location_weight"] = df["location"].apply(lambda x: location_weight(x, cfg))
    df["location_score"] = df.apply(
        lambda r: location_tier(r["location"], r["description"], cfg),
        axis=1,
    )
    df["recency_weight"] = df["date_posted"].apply(lambda d: recency_weight(cfg, d))

    user_yoe = cfg.get("experience", {}).get("max_yoe")
    df["seniority_score"] = df.apply(
        lambda r: calculate_seniority_score(
            cfg, title=r["title"], description=r["description"], user_yoe=user_yoe,
        ),
        axis=1,
    )
    penalties = cfg.get("ranking", {}).get("functional_role_penalties", {})
    df["functional_role_penalty"] = df["functional_role"].map(penalties).fillna(1.0)

    df = _apply_additive_scoring(df, cfg)
    df = await _apply_agentic_matching(
        df,
        cfg=cfg,
        user_id=user_id,
        resume_text=resume_text,
        profile=profile,
        db=db,
        llm_client=llm_client,
    )

    return _finalize_ranked_dataframe(df, user_id, role_intent=effective_role_intent, duration_s=time.monotonic() - t_total)


def _finalize_ranked_dataframe(
    df: pd.DataFrame,
    user_id: str,
    *,
    role_intent: str,
    duration_s: float | None = None,
) -> pd.DataFrame:
    df = df.sort_values("final_score", ascending=False).drop_duplicates(subset=["job_url"])
    df["_dedup_key"] = (
        df["title"].str.strip().str.lower() + "|" + df["company"].str.strip().str.lower()
    )
    df = df.drop_duplicates(subset="_dedup_key", keep="first")
    df["_fuzzy_key"] = (
        df["title"].str.strip().str.lower()
        .str.replace(_SENIORITY_SUFFIXES, "", regex=True)
        .str.strip() + "|" + df["company"].str.strip().str.lower()
    )
    df = df.drop_duplicates(subset="_fuzzy_key", keep="first")
    df = df.drop(columns=["_dedup_key", "_fuzzy_key"], errors="ignore").reset_index(drop=True)
    df = df.drop(columns=["description", "role_clusters", "embedding"], errors="ignore")
    release_memory(logger, "rank_finalize_release", jobs=len(df))

    logger.info(
        "Ranking complete",
        extra={
            "user_id": user_id,
            "input_jobs": len(df),
            "duration_s": round(duration_s, 2) if duration_s is not None else None,
            "role_intent": role_intent,
        },
    )
    log_rss(logger, "rank_complete", user_id=user_id, jobs=len(df))
    return df
