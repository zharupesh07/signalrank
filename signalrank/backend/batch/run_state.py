from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from batch.run_progress import run_progress_meta


async def mark_run_cancelled(
    update_run_row,
    session_factory: async_sessionmaker,
    run_id: str,
    *,
    claim_token: str | None = None,
) -> bool:
    return await update_run_row(
        session_factory,
        run_id,
        claim_token=claim_token,
        values={
            "status": "cancelled",
            "finished_at": datetime.now(timezone.utc),
            "claim_token": None,
            "claimed_by": None,
            "lease_expires_at": None,
        },
    )


async def mark_run_failed(
    update_run_row,
    session_factory: async_sessionmaker,
    run_id: str,
    *,
    mode: str,
    force_scrape: bool,
    disable_scraping: bool,
    error: str,
    claim_token: str | None = None,
    auto_refresh: bool = False,
    scrape_executed: bool | None = None,
    scrape_reason: str | None = None,
) -> bool:
    return await update_run_row(
        session_factory,
        run_id,
        claim_token=claim_token,
        values={
            "status": "failed",
            "finished_at": datetime.now(timezone.utc),
            "progress": run_progress_meta(
                mode,
                force_scrape,
                disable_scraping,
                auto_refresh=auto_refresh,
                scrape_executed=scrape_executed,
                scrape_reason=scrape_reason,
            ),
            "error": error,
            "claim_token": None,
            "claimed_by": None,
            "lease_expires_at": None,
        },
    )
