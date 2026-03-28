import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw
from batch.context import build_context
from batch.embedding_cache import PgEmbeddingCache
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
)
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



_JOB_WINDOW_DAYS = 15


async def load_jobs_dataframe(
    db: AsyncSession,
    role_clusters: set[str] | None = None,
) -> pd.DataFrame:
    from sqlalchemy import cast, or_
    from sqlalchemy.dialects.postgresql import JSONB

    cutoff = datetime.now(timezone.utc) - timedelta(days=_JOB_WINDOW_DAYS)
    stmt = select(
        JobRaw.id, JobRaw.job_url, JobRaw.title, JobRaw.company,
        func.left(JobRaw.description, 2000).label("description"),
        JobRaw.location, JobRaw.site, JobRaw.date_posted,
    ).where(JobRaw.ingested_at >= cutoff)

    if role_clusters and "general" not in role_clusters:
        cluster_conditions = [
            JobRaw.role_clusters.is_(None),
            JobRaw.role_clusters == cast([], JSONB),
            *[JobRaw.role_clusters.contains(cast([c], JSONB)) for c in role_clusters],
        ]
        stmt = stmt.where(or_(*cluster_conditions))

    stmt = stmt.limit(5000)

    result = await db.execute(stmt)
    rows = result.all()
    if not rows:
        return pd.DataFrame(
            columns=["id", "job_url", "title", "company", "description",
                     "location", "site", "date_posted"]
        )
    return pd.DataFrame(
        rows,
        columns=["id", "job_url", "title", "company", "description",
                 "location", "site", "date_posted"],
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


_RANK_EMBED_CHUNK = 64


async def _compute_embeddings(
    df: pd.DataFrame,
    cfg: dict,
    db: AsyncSession,
    cfg_fp: str,
    resume_text: str,
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

    job_texts = [
        build_job_embedding_text(title=t, description=d, canonical_skills=cs, cfg=cfg)
        for t, d, cs in zip(df["title"], df["description"], df["canonical_skills"])
    ]
    job_fps = [fingerprint_text(t) for t in job_texts]
    cached = await job_cache.fetch(job_fps)

    dim = cfg["embeddings"]["embedding_dim"]
    vectors = np.zeros((len(job_fps), dim), dtype="float32")
    misses = []
    for i, fp in enumerate(job_fps):
        if fp in cached:
            vectors[i] = np.array(cached[fp], dtype="float32")
        else:
            misses.append(i)

    logger.info("Embedding cache: %d hits, %d misses out of %d jobs",
                len(cached), len(misses), len(job_fps))

    engine = None
    if misses:
        engine = EmbeddingEngine(cfg)
        total = len(misses)
        for chunk_start in range(0, total, _RANK_EMBED_CHUNK):
            chunk_end = min(chunk_start + _RANK_EMBED_CHUNK, total)
            chunk_indices = misses[chunk_start:chunk_end]
            chunk_texts = [job_texts[i] for i in chunk_indices]

            new_vecs = await asyncio.to_thread(engine.embed, chunk_texts)

            await job_cache.store_vectors(
                [(job_fps[i], v.tolist()) for i, v in zip(chunk_indices, new_vecs)]
            )
            await db.commit()

            for i, v in zip(chunk_indices, new_vecs):
                vectors[i] = v

            logger.info("Ranking embed: %d/%d", chunk_end, total)

    resume_emb_text = build_resume_embedding_text(
        resume_text=resume_text,
        distilled=distilled_text or cfg.get("resume", {}).get("distilled_text"),
        cfg=cfg,
        use_case="default",
    )
    resume_fp = fingerprint_text(resume_emb_text)
    resume_cached = await resume_cache.fetch([resume_fp])

    if resume_fp in resume_cached:
        r_emb = np.array(resume_cached[resume_fp], dtype="float32")
    else:
        if engine is None:
            engine = EmbeddingEngine(cfg)
        r_emb = (await asyncio.to_thread(engine.embed, [resume_emb_text]))[0]
        await resume_cache.store_vectors([(resume_fp, r_emb.tolist())])

    df["semantic_score"] = cosine_similarity(r_emb, vectors)
    logger.info(
        "Embeddings computed",
        extra={"jobs": len(df), "cache_misses": len(misses),
               "duration_s": round(time.monotonic() - t_emb, 2)},
    )
    return df


async def score_jobs_for_user(
    db: AsyncSession,
    user_id: str,
    resume_text: str,
    config_overrides: dict | None,
    distilled_text: str | None = None,
) -> pd.DataFrame:
    from domain.role_clusters import roles_to_clusters

    t_total = time.monotonic()
    ctx = build_context(user_id, resume_text, config_overrides)
    cfg = ctx.config

    profile_roles = cfg.get("profile_intent", {}).get("roles", [])
    clusters = roles_to_clusters(profile_roles) if profile_roles else None

    df = await load_jobs_dataframe(db, role_clusters=clusters)
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    df = _apply_pre_filters(df, cfg)
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    role_intent = (
        cfg.get("profile_intent", {}).get("preset")
        or cfg.get("ranking", {}).get("default_role")
        or "software_general"
    )

    df = await _compute_embeddings(df, cfg, db, ctx.config_fp, resume_text, distilled_text=distilled_text)

    df = _apply_semantic_gates(df, cfg, role_intent)
    if df.empty:
        return pd.DataFrame(columns=["final_score"])

    df["semantic_score"] *= df["skill_overlap"].apply(bounded_skill_boost)

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

    logger.info(
        "Ranking complete",
        extra={"user_id": user_id, "input_jobs": len(df), "duration_s": round(time.monotonic() - t_total, 2)},
    )
    return df
