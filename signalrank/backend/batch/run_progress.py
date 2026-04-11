from typing import Any

from batch.run_kinds import run_kind_from_flags


def progress_str(progress: Any, key: str) -> str | None:
    if not isinstance(progress, dict):
        return None
    value = progress.get(key)
    return str(value) if value is not None and value != "" else None


def progress_int(progress: Any, key: str) -> int | None:
    if not isinstance(progress, dict):
        return None
    value = progress.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def corpus_progress(
    *,
    corpus_source: str | None = None,
    corpus_job_count: int | None = None,
    scored_job_count: int | None = None,
    shown_job_count: int | None = None,
) -> dict[str, int | str]:
    progress: dict[str, int | str] = {}
    if corpus_source:
        progress["corpus_source"] = corpus_source
    if corpus_job_count is not None:
        progress["corpus_job_count"] = int(corpus_job_count)
    if scored_job_count is not None:
        progress["scored_job_count"] = int(scored_job_count)
    if shown_job_count is not None:
        progress["shown_job_count"] = int(shown_job_count)
    return progress


def run_progress_meta(
    mode: str,
    force_scrape: bool,
    disable_scraping: bool,
    *,
    auto_refresh: bool = False,
    scrape_executed: bool | None = None,
    scrape_reason: str | None = None,
) -> dict:
    progress = {
        "requested_mode": mode,
        "force_scrape": force_scrape,
        "disable_scraping": disable_scraping,
        "run_kind": run_kind_from_flags(
            force_scrape=force_scrape,
            disable_scraping=disable_scraping,
            auto_refresh=auto_refresh,
        ),
    }
    if auto_refresh:
        progress["auto_refresh"] = True
    if scrape_executed is not None:
        progress["scrape_executed"] = scrape_executed
    if scrape_reason:
        progress["scrape_reason"] = scrape_reason
    return progress


def merge_run_progress(
    mode: str,
    force_scrape: bool,
    disable_scraping: bool,
    *,
    auto_refresh: bool = False,
    scrape_executed: bool | None = None,
    scrape_reason: str | None = None,
    **kwargs,
) -> dict:
    progress = run_progress_meta(
        mode,
        force_scrape,
        disable_scraping,
        auto_refresh=auto_refresh,
        scrape_executed=scrape_executed,
        scrape_reason=scrape_reason,
    )
    progress.update(kwargs)
    return progress
