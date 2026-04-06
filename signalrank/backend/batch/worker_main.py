"""
Standalone ranking worker entrypoint.

Modes:
  poll           — continuous poll loop (default, for Docker/Railway deployment)
  enqueue-cron   — insert pending runs for all active profiles, then exit

Usage:
  uv run python -m batch.worker_main poll
  uv run python -m batch.worker_main poll --once
  uv run python -m batch.worker_main poll --scan-modes full
  uv run python -m batch.worker_main enqueue-cron

Environment variables:
  DATABASE_URL          — primary DB URL (asyncpg format)
  DATABASE_URL_RAILWAY  — Railway internal DB URL (takes precedence if set)
  OPENROUTER_API_KEY    — required for LLM-based ranking/verification
  RUN_API_WORKER        — must be "false" when running as standalone worker
  WORKER_SCAN_MODES     — space-separated scan modes (default: quick full)
  WORKER_CONCURRENCY    — number of concurrent runs (default: 1)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worker_main",
        description="SignalRank standalone ranking worker",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    poll_p = sub.add_parser("poll", help="Poll DB for pending runs continuously")
    poll_p.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Exit after processing one batch of available runs (useful for CI/testing)",
    )
    poll_p.add_argument(
        "--scan-modes",
        nargs="+",
        default=os.environ.get("WORKER_SCAN_MODES", "quick full").split(),
        metavar="MODE",
        help="Scan modes to handle (default: quick full)",
    )
    poll_p.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("WORKER_CONCURRENCY", "1")),
        help="Max concurrent runs (default: 1)",
    )

    sub.add_parser("enqueue-cron", help="Enqueue pending runs for all active profiles and exit")

    return parser


def resolve_db_url() -> str:
    """Return the DB URL to use, preferring DATABASE_URL_RAILWAY if set."""
    railway = os.environ.get("DATABASE_URL_RAILWAY", "").strip()
    if railway:
        return _ensure_asyncpg(railway)
    primary = os.environ.get("DATABASE_URL", "").strip()
    if not primary:
        raise RuntimeError("DATABASE_URL is not set")
    return _ensure_asyncpg(primary)


def _ensure_asyncpg(url: str) -> str:
    """Rewrite postgresql:// to postgresql+asyncpg:// if needed."""
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    return url


async def _run_poll(args: argparse.Namespace) -> None:
    from api.database import _build_engine
    from batch.worker import worker_loop, _worker_loop_for_mode

    db_url = resolve_db_url()
    _, session_factory = _build_engine(db_url)

    if args.once:
        sem = asyncio.Semaphore(args.concurrency)

        async def _run_with_sem(mode: str) -> None:
            async with sem:
                await _worker_loop_for_mode(session_factory, mode)

        await asyncio.gather(*[_run_with_sem(mode) for mode in args.scan_modes])
    else:
        await worker_loop(session_factory)


async def _run_enqueue_cron(args: argparse.Namespace) -> None:
    from api.database import _build_engine
    from api.models import Profile, Run
    from sqlalchemy import select

    db_url = resolve_db_url()
    _, session_factory = _build_engine(db_url)

    async with session_factory() as session:
        result = await session.execute(
            select(Profile).where(Profile.onboarding_complete == True)  # noqa: E712
        )
        profiles = result.scalars().all()
        enqueued = 0
        skipped = 0
        for profile in profiles:
            active_result = await session.execute(
                select(Run).where(
                    Run.user_id == profile.user_id,
                    Run.status.in_(["pending", "claimed", "scraping", "ranking"]),
                )
            )
            if active_result.scalar_one_or_none():
                skipped += 1
                continue
            run = Run(
                user_id=profile.user_id,
                status="pending",
                mode="full",
                trigger_source="cron",
                progress={"requested_mode": "full", "force_scrape": False, "disable_scraping": False},
            )
            session.add(run)
            enqueued += 1
        await session.commit()
        logger.info("Cron enqueue: %d enqueued, %d skipped (already active)", enqueued, skipped)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args()

    os.environ.setdefault("RUN_API_WORKER", "false")

    if args.mode == "poll":
        asyncio.run(_run_poll(args))
    elif args.mode == "enqueue-cron":
        asyncio.run(_run_enqueue_cron(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
