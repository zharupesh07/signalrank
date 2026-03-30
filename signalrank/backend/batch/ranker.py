import asyncio
import gc
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, Profile
from api.config import settings
from batch.context import build_context, get_batch, load_base_config
from batch.embedding_cache import PgEmbeddingCache, store_job_embeddings
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
from domain.profile_rules import enrich_config_with_profile_rules, title_rule_flags
from domain.profile_rules import text_matches_profile_positive_terms
from domain.roles import (
    classify_functional_role,
    consulting_dampener,
    requires_high_semantic_floor,
)
from domain.scoring import (
    calculate_role_and_skill_match_score,
    calculate_seniority_score,
    extract_required_yoe,
    location_weight,
    recency_weight,
)
from domain.skill_boost import bounded_skill_boost
from domain.skills import SkillCanonicalizer, extract_skills_from_texts

logger = logging.getLogger(__name__)



_JOB_WINDOW_DAYS = load_base_config().get("batch", {}).get("job_window_days", 15)
_RANK_MAX_CANDIDATES = settings.ranker_max_candidates
_RANK_DESCRIPTION_CHARS = settings.ranker_max_description_chars


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
) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    stmt = select(
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, _RANK_DESCRIPTION_CHARS).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted, JobRaw.role_clusters, JobRaw.embedding,
    ).where(JobRaw.ingested_at >= cutoff)

    stmt = stmt.limit(_RANK_MAX_CANDIDATES)

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
        JobRaw.location, JobRaw.site, JobRaw.date_posted, JobRaw.role_clusters, JobRaw.embedding,
    ).where(JobRaw.id.in_(job_ids))
    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return pd.DataFrame(
            columns=["id", "job_url", "title", "company", "description",
                     "location", "site", "date_posted", "role_clusters", "embedding"]
        )
    return pd.DataFrame(
        rows,
        columns=["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted", "role_clusters", "embedding"],
    )


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

    positive_terms = (cfg.get("ranking", {}) or {}).get("profile_positive_terms", [])
    if positive_terms:
        positive_mask = df.apply(
            lambda r: text_matches_profile_positive_terms(
                f"{r['title'] or ''} {r['description'] or ''}",
                cfg,
            ),
            axis=1,
        )
        mask &= positive_mask

    out = df.loc[mask].reset_index(drop=True)
    out["description_quality"] = desc_quality.loc[mask].values
    return out


def _apply_additive_scoring(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()

    # Skills score — vectorized
    damp = df["title"].apply(consulting_dampener)
    base = df["semantic_score"] * 100
    base = base + np.minimum(df["skill_overlap"] * 2, 8)
    role_mod = np.clip((df["role_skill_score"] - 1.0) * 25, -10, 10)
    base = base + role_mod
    func_mod = np.clip((df["functional_role_penalty"] - 1.0) * 50, -8, 10)
    base = base + func_mod
    base = base - (damp < 1.0).astype(float) * 10
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

    # Seniority — vectorized
    df["seniority_score_dim"] = np.clip(((df["seniority_score"] - 0.4) / 0.75) * 90 + 10, 0, 100)

    # Location — vectorized
    df["location_score"] = np.where(df["location_weight"] > 1.0, 100.0, 30.0)

    # Recency — still per-row (date parsing)
    df["recency_score"] = df["date_posted"].apply(recency_score_0_100)

    # Weighted final score — vectorized
    w = cfg.get("ranking", {}).get("scoring_weights", {})
    df["final_score"] = (
        df["skills_score"] * w.get("skills_match", 0.40)
        + df["company_score"] * w.get("company_fit", 0.20)
        + df["seniority_score_dim"] * w.get("seniority", 0.15)
        + df["location_score"] * w.get("location", 0.15)
        + df["recency_score"] * w.get("recency", 0.10)
    ).fillna(0.0)

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

    # Contract penalty — vectorized
    contract_penalty = cfg.get("ranking", {}).get("contract_penalty", 0.9)
    df["is_contract"] = df.apply(
        lambda r: detect_contract_type(r["title"], r["description"]), axis=1,
    )
    df.loc[df["is_contract"], "final_score"] *= contract_penalty
    return df


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
) -> pd.DataFrame:
    t_emb = time.monotonic()

    # Use __base__ cfg_fp for job embeddings so pre-embed cache is reusable
    base_ctx = build_context(user_id="__base__", resume_text="")
    job_cache = PgEmbeddingCache(db, base_ctx.config_fp)
    # User-specific cache for resume embedding
    resume_cache = PgEmbeddingCache(db, cfg_fp)

    raw_skills = extract_skills_from_texts(df["description"].fillna("").tolist(), cfg)
    canon = SkillCanonicalizer(cfg)
    df["canonical_skills"] = [sorted(canon.canonicalize(s)) for s in raw_skills]
    df["skill_overlap"] = df["canonical_skills"].apply(len)

    dim = cfg["embeddings"]["embedding_dim"]
    vectors = np.zeros((len(df), dim), dtype="float32")
    stored_hits = 0
    miss_specs: list[tuple[int, str, str]] = []
    for i, (t, d, cs, stored_embedding) in enumerate(
        zip(df["title"], df["description"], df["canonical_skills"], df["embedding"])
    ):
        if stored_embedding is not None:
            vectors[i] = np.array(stored_embedding, dtype="float32")
            stored_hits += 1
            continue
        job_text = build_job_embedding_text(title=t, description=d, canonical_skills=cs, cfg=cfg)
        miss_specs.append((i, fingerprint_text(job_text), job_text))

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

    engine = None
    if misses:
        engine = EmbeddingEngine(cfg)
        total = len(misses)
        cache_rows: list[tuple[str, list[float]]] = []
        job_embedding_rows: list[tuple[str, list[float]]] = []
        rank_embed_chunk = get_batch(cfg, "rank_embed_chunk", 4)
        for chunk_start in range(0, total, rank_embed_chunk):
            chunk_end = min(chunk_start + rank_embed_chunk, total)
            chunk = misses[chunk_start:chunk_end]
            chunk_texts = [miss_text_by_row_idx[row_idx] for row_idx, _ in chunk]

            new_vecs = await asyncio.to_thread(engine.embed, chunk_texts)

            for (row_idx, text_fp), v in zip(chunk, new_vecs):
                vector = v.tolist()
                cache_rows.append((text_fp, vector))
                job_embedding_rows.append((df.at[row_idx, "job_url"], vector))
                vectors[row_idx] = v

            logger.info("Ranking embed: %d/%d", chunk_end, total)

        await job_cache.store_vectors(cache_rows)
        await store_job_embeddings(db, cached_job_rows + job_embedding_rows)
        await db.commit()
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
    logger.info(
        "Embeddings computed",
        extra={"jobs": len(df), "cache_misses": len(misses),
               "duration_s": round(time.monotonic() - t_emb, 2)},
    )
    df = df.drop(columns=["canonical_skills"], errors="ignore")
    del vectors, cached, raw_skills, canon
    del miss_specs, miss_text_by_row_idx
    if "new_vecs" in locals():
        del new_vecs
    if "r_emb" in locals():
        del r_emb
    unload_embedding_engine()
    gc.collect()
    return df


async def score_jobs_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
) -> pd.DataFrame:
    from domain.role_clusters import roles_to_clusters
    ctx = build_context(user_id, resume_text, config_overrides)
    profile_roles = ctx.config.get("profile_intent", {}).get("roles", [])
    clusters = roles_to_clusters(profile_roles) if profile_roles else None
    df = await load_jobs_dataframe(db, role_clusters=clusters)
    return await _score_loaded_jobs_dataframe(
        db=db,
        df=df,
        user_id=user_id,
        resume_text=resume_text,
        config_overrides=config_overrides,
        distilled_text=distilled_text,
    )


async def score_job_ids_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    job_ids: list[str],
    config_overrides: dict | None,
    distilled_text: str | None = None,
) -> pd.DataFrame:
    df = await load_jobs_by_ids_dataframe(db, job_ids)
    return await _score_loaded_jobs_dataframe(
        db=db,
        df=df,
        user_id=user_id,
        resume_text=resume_text,
        config_overrides=config_overrides,
        distilled_text=distilled_text,
    )


async def _score_loaded_jobs_dataframe(
    db: AsyncSession,
    df: pd.DataFrame,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
) -> pd.DataFrame:
    t_total = time.monotonic()
    ctx = build_context(user_id, resume_text, config_overrides)
    cfg = ctx.config

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

    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    df = _apply_pre_filters(df, cfg)
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    pre_dedupe_count = len(df)
    df = _dedupe_before_embedding(df)
    if len(df) != pre_dedupe_count:
        logger.info("Pre-embedding dedupe removed %d duplicate rows", pre_dedupe_count - len(df))

    role_intent = (
        cfg.get("profile_intent", {}).get("preset")
        or cfg.get("ranking", {}).get("default_role")
        or "software_general"
    )

    persisted_resume_embedding = None
    if _is_uuid_like(user_id):
        profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
        profile = profile_result.scalar_one_or_none()
        if profile and profile.resume_embedding is not None:
            persisted_resume_embedding = list(profile.resume_embedding)

    df = await _compute_embeddings(
        df,
        cfg,
        db,
        ctx.config_fp,
        user_id,
        resume_text,
        persisted_resume_embedding=persisted_resume_embedding,
        distilled_text=distilled_text,
    )

    df = _apply_semantic_gates(df, cfg, role_intent)
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
    gc.collect()

    logger.info(
        "Ranking complete",
        extra={"user_id": user_id, "input_jobs": len(df), "duration_s": round(time.monotonic() - t_total, 2)},
    )
    return df
