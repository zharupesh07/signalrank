#!/usr/bin/env python3
# ================================
# FILE: build_corpus.py
# ================================
import argparse
import re
from pathlib import Path

import pandas as pd
from config_loader import load_effective_settings, settings
from llm.classify_role import classify_roles_batch
from logger import setup_logger
from profiles import PROFILES
from user_context import resolve_user_context
from utils.timing import timed

logger = setup_logger()

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
FALLBACK_COLS = ["company", "title", "location"]
DROP_IF_NULL = ["title", "company", "description"]


def normalize_date(val):
    try:
        return pd.to_datetime(val, utc=True).isoformat()
    except Exception:
        return None


def row_key(row):
    if pd.notna(row.get("job_url")) and row.get("job_url"):
        return row["job_url"].strip().lower()
    return "|".join(str(row.get(c, "")).strip().lower() for c in FALLBACK_COLS)


def apply_profile_filters(df: pd.DataFrame, profile, logger) -> pd.DataFrame:
    """
    Apply corpus-level filters with DEBUG COUNTERS.

    Practical corpus policy:
    - Enforce IC-only
    - Enforce no managers
    - DO NOT keyword-filter descriptions
    - Only title-based exclusions apply
    """

    total_before = len(df)

    # ---------------------------------
    # Role classification
    # ---------------------------------
    roles = classify_roles_batch(df["title"].tolist(), logger=logger)
    df = df.copy()
    df["role"] = roles

    # ---------------------------------
    # Drop junior roles
    # ---------------------------------
    before = len(df)
    if profile.skip_junior_roles:
        df = df[df["role"] != "junior"]
    dropped_junior = before - len(df)

    # ---------------------------------
    # Drop manager roles
    # ---------------------------------
    before = len(df)
    if profile.skip_manager_roles:
        df = df[df["role"] != "manager"]
    dropped_manager = before - len(df)

    # ---------------------------------
    # TITLE-ONLY keyword exclusions (RELAXED)
    # ---------------------------------
    before = len(df)
    title_exclude = set(k.lower() for k in profile.exclude_keywords)

    def title_blocked(title: str) -> bool:
        if not isinstance(title, str):
            return False
        t = title.lower()
        return any(k in t for k in title_exclude)

    df = df[~df["title"].apply(title_blocked)]
    dropped_title_kw = before - len(df)

    # ---------------------------------
    # DEBUG SUMMARY (NO BEHAVIOR CHANGE)
    # ---------------------------------
    total_after = len(df)

    logger.info(
        "[CORPUS FILTER DEBUG] "
        f"start={total_before} | "
        f"junior_dropped={dropped_junior} | "
        f"manager_dropped={dropped_manager} | "
        f"title_kw_dropped={dropped_title_kw} | "
        f"final={total_after}"
    )

    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--use-case", help="Use case (optional)")
    args = parser.parse_args()

    # --------------------------------------------------
    # USER-SCOPED ONLY
    # --------------------------------------------------
    ctx = resolve_user_context(
        user=args.user,
        use_case_override=args.use_case,
        require_resume=False,
    )

    # --------------------------------------------------
    # Load effective config (single source of truth)
    # --------------------------------------------------
    effective_cfg = load_effective_settings(ctx)
    from core.pipeline_context import resolve_profile_name

    profile_name = resolve_profile_name(effective_cfg)
    if profile_name not in PROFILES:
        raise SystemExit(f"Unknown profile: {profile_name}")

    profile = PROFILES[profile_name]

    corpus_dir = ctx.corpus_dir
    cache_dir = ctx.cache_dir
    corpus_dir.mkdir(parents=True, exist_ok=True)

    output_path = corpus_dir / "jobs_corpus.csv"

    logger.info(
        f"[CORPUS] User={ctx.user} use_case={ctx.use_case} profile={profile_name}"
    )
    logger.info(f"[CORPUS] Writing → {output_path}")

    # --------------------------------------------------
    # Load cached job CSVs
    # --------------------------------------------------
    csvs = list(cache_dir.glob("query_*.csv"))
    if not csvs:
        logger.error("No cached query CSVs found")
        return

    frames = []
    for p in csvs:
        try:
            df = pd.read_csv(p)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            logger.warning(f"Failed to read {p}: {e}")

    if not frames:
        logger.error("All cached CSVs empty or unreadable")
        return

    df = pd.concat(frames, ignore_index=True)

    for c in DROP_IF_NULL:
        df = df[df[c].notna()]

    logger.info(f"[CORPUS] Rows before filtering: {len(df)}")

    # --------------------------------------------------
    # Apply profile filters
    # --------------------------------------------------
    with timed("Corpus role classification", logger):
        df = apply_profile_filters(df, profile, logger)

    # --------------------------------------------------
    # Deduplication
    # --------------------------------------------------
    df["_dedupe_key"] = df.apply(row_key, axis=1)

    if "date_posted" in df.columns:
        df["_date_norm"] = df["date_posted"].apply(normalize_date)
        df = df.sort_values("_date_norm", ascending=False)

    with timed("Corpus deduplication", logger):
        deduped = df.drop_duplicates(subset="_dedupe_key", keep="first").reset_index(
            drop=True
        )

    if "date_posted" in deduped.columns:
        deduped["date_posted"] = deduped["date_posted"].apply(normalize_date)

    # --------------------------------------------------
    # Strip ranking-only columns
    # --------------------------------------------------
    for col in [
        "semantic_score",
        "company_weight",
        "low_priority_penalty",
        "final_score",
    ]:
        if col in deduped.columns:
            deduped.drop(columns=[col], inplace=True)
    # Ensure at least one apply URL exists
    if "job_url" not in deduped.columns:
        deduped["job_url"] = None

    if "job_url_direct" not in deduped.columns:
        deduped["job_url_direct"] = None
    deduped.to_csv(output_path, index=False)
    logger.info(f"[CORPUS] Corpus built: {len(deduped)} jobs")


if __name__ == "__main__":
    main()
