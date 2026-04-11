from typing import Any


RUN_KIND_RERANK_ONLY = "rerank_only"
RUN_KIND_AUTO_REFRESH = "auto_refresh"
RUN_KIND_MANUAL_REFRESH = "manual_refresh"
RUN_KIND_MANUAL_RUN = "manual_run"


def run_kind_from_flags(
    *,
    force_scrape: bool,
    disable_scraping: bool,
    auto_refresh: bool = False,
) -> str:
    if disable_scraping:
        return RUN_KIND_RERANK_ONLY
    if auto_refresh:
        return RUN_KIND_AUTO_REFRESH
    if force_scrape:
        return RUN_KIND_MANUAL_REFRESH
    return RUN_KIND_MANUAL_RUN


def run_kind_from_progress(progress: Any) -> str | None:
    if not isinstance(progress, dict):
        return None
    value = progress.get("run_kind")
    return str(value) if value else None


def scrape_reason_from_progress(progress: Any) -> str | None:
    if not isinstance(progress, dict):
        return None
    value = progress.get("scrape_reason")
    return str(value) if value else None
