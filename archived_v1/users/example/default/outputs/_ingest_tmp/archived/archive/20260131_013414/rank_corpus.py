#!/usr/bin/env python3
# ================================
# FILE: rank_corpus.py
# ================================
import argparse
from pathlib import Path

import pandas as pd
from config_loader import fingerprint_settings, load_effective_settings
from core.pipeline_context import resolve_profile_name
from embeddings.embedding_cache import EmbeddingCache
from llm.normalize_skills import normalize_skills_batch
from logger import setup_logger
from match_engine import rank_jobs
from profiles import PROFILES
from resume_parser import load_resume
from skills.canonicalizer import canonicalize_skills
from user_context import resolve_user_context

logger = setup_logger()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--use-case", help="Use case (optional)")
    args = parser.parse_args()

    # --------------------------------------------------
    # Resolve user context (USER-SCOPED ONLY)
    # --------------------------------------------------
    ctx = resolve_user_context(
        user=args.user,
        use_case_override=args.use_case,
        require_resume=True,
    )

    effective_cfg = load_effective_settings(ctx)

    profile_name = resolve_profile_name(effective_cfg)
    if profile_name not in PROFILES:
        raise SystemExit(f"Unknown profile: {profile_name}")

    profile = PROFILES[profile_name]
    profile.workspace_dir = str(ctx.base_dir / "workspace")

    corpus_path = ctx.corpus_dir / "jobs_corpus.csv"
    faiss_dir = ctx.base_dir / "embeddings"
    output_dir = ctx.corpus_dir

    faiss_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"[CORPUS RANK] User={ctx.user} use_case={ctx.use_case} profile={profile_name}"
    )

    if not corpus_path.exists():
        logger.error(f"{corpus_path} not found. Run build_corpus.py first.")
        return

    df = pd.read_csv(corpus_path)
    if df.empty:
        logger.error("Corpus is empty")
        return

    logger.info(f"[CORPUS RANK] Ranking {len(df)} corpus jobs")

    # --------------------------------------------------
    # Load FAISS embeddings (read-only)
    # --------------------------------------------------

    raw_skills = normalize_skills_batch(
        df["description"].fillna("").tolist(),
        effective_settings=effective_cfg,
        logger=logger,
    )

    cfg_fp = fingerprint_settings(effective_cfg)

    texts = [
        " ".join(
            sorted(
                canonicalize_skills(
                    skills,
                    effective_settings=effective_cfg,
                    cfg_fingerprint=cfg_fp,
                )
            )
        )
        for skills in raw_skills
    ]

    cache = EmbeddingCache(
        dim=effective_cfg["embeddings"]["embedding_dim"],
        cache_dir=str(faiss_dir),
        cfg_fingerprint=cfg_fp,
        logger=logger,
    )

    found, missing = cache.lookup(texts)
    if missing:
        logger.error(
            f"[CORPUS RANK] {len(missing)} embeddings missing.\n"
            "Run build_faiss_corpus.py first."
        )
        return

    resume_text = load_resume(str(ctx.resume_path))

    ranked = rank_jobs(
        resume_text=resume_text,
        jobs_df=df,
        preferences={"preferred": [], "deprioritized": []},
        profile=profile,
        logger=logger,
        effective_settings=effective_cfg,
        allow_embedding=False,
        embedding_cache_dir=str(faiss_dir),
        ctx=ctx,
    )

    output_path = output_dir / "ranked_corpus.csv"
    ranked.to_csv(output_path, index=False)
    logger.info(f"[CORPUS RANK] Saved → {output_path}")


if __name__ == "__main__":
    main()
