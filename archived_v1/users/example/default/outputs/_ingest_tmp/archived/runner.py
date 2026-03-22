import hashlib
from datetime import datetime
from pathlib import Path

from logger import setup_logger
from match_engine import rank_jobs
from resume_parser import latex_to_text
from scrape_jobs import fetch_jobs


def run_job_ranking(
    *,
    resume_path: str,
    search_query: str,
    country: str,
    hours_old: int,
    remote_only: bool,
    preferences: dict,
    force_refresh: bool,
    logger=None,
    job_limit: int = 100,
    output_base: Path = Path("outputs"),
):
    if logger is None:
        logger = setup_logger()

    logger.info("Loading resume")
    resume_text = latex_to_text(resume_path)
    resume_hash = hashlib.sha256(resume_text.encode()).hexdigest()[:8]

    logger.info("Fetching jobs")
    jobs_df = fetch_jobs(
        search_term=search_query,
        country=country,
        hours_old=hours_old,
        remote_only=remote_only,
        results_wanted=job_limit,
        force_refresh=force_refresh,
        logger=logger,
    )

    if jobs_df.empty:
        logger.warning("No jobs fetched")
        return None, None

    logger.info("Ranking jobs")
    ranked = rank_jobs(resume_text, jobs_df, preferences, logger)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = output_base / "users" / f"resume_{resume_hash}" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    output_file = run_dir / f"ranked_jobs__{country}__h{hours_old}.csv"
    ranked.to_csv(output_file, index=False)

    logger.info(f"Saved results to {output_file}")
    return ranked, output_file
