"""Dedup store — remembers which job URLs we've already emailed.

A standalone table (no signalrank FKs, no user rows) keyed by job_url. Before a
run we load the sent set; after sending we record the new URLs. This is what
stops the same job appearing in the digest day after day.

Uses the same DATABASE_URL (Neon) as the rest of the pipeline.
"""
from __future__ import annotations

import os
import ssl

import asyncpg

DDL = """
CREATE TABLE IF NOT EXISTS digest_sent (
    job_url   TEXT PRIMARY KEY,
    title     TEXT,
    company   TEXT,
    sent_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _dsn() -> str:
    """Neon URL -> asyncpg-friendly DSN (strip sslmode; asyncpg takes ssl separately)."""
    url = os.environ["DATABASE_URL"]
    # asyncpg wants plain postg:// and no sslmode/channel_binding query args
    import re
    url = re.sub(r"^postgresql\+\w+://", "postgresql://", url)
    url = re.sub(r"[?&](sslmode|channel_binding|ssl)=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    return url


async def _connect():
    ctx = ssl.create_default_context()
    return await asyncpg.connect(_dsn(), ssl=ctx)


async def ensure_table() -> None:
    conn = await _connect()
    try:
        await conn.execute(DDL)
    finally:
        await conn.close()


async def load_sent_urls() -> set[str]:
    """Return the set of job URLs already emailed (across all past runs)."""
    conn = await _connect()
    try:
        await conn.execute(DDL)  # idempotent — safe on first run
        rows = await conn.fetch("SELECT job_url FROM digest_sent")
        return {r["job_url"] for r in rows}
    finally:
        await conn.close()


async def already_ran_today(tag: str, day: str) -> bool:
    """True if a digest for this tag (e.g. config name) already ran on `day` (YYYY-MM-DD)."""
    from datetime import date as _date
    day_obj = _date.fromisoformat(day)
    conn = await _connect()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS digest_runs ("
            "  tag TEXT NOT NULL, run_day DATE NOT NULL,"
            "  ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (tag, run_day))"
        )
        row = await conn.fetchrow(
            "SELECT 1 FROM digest_runs WHERE tag = $1 AND run_day = $2", tag, day_obj
        )
        return row is not None
    finally:
        await conn.close()


async def mark_ran_today(tag: str, day: str) -> None:
    from datetime import date as _date
    day_obj = _date.fromisoformat(day)
    conn = await _connect()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS digest_runs ("
            "  tag TEXT NOT NULL, run_day DATE NOT NULL,"
            "  ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (tag, run_day))"
        )
        await conn.execute(
            "INSERT INTO digest_runs (tag, run_day) VALUES ($1, $2) "
            "ON CONFLICT (tag, run_day) DO NOTHING", tag, day_obj
        )
    finally:
        await conn.close()


async def load_seen_urls() -> set[str]:
    """All job URLs we've EVER scored (emailed or not) — so we never re-score them."""
    conn = await _connect()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_jobs ("
            "  job_url TEXT PRIMARY KEY, verdict TEXT,"
            "  scored_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        rows = await conn.fetch("SELECT job_url FROM seen_jobs")
        return {r["job_url"] for r in rows}
    finally:
        await conn.close()


async def record_seen(scored: list) -> int:
    """Record every scored job (band, job, report) so future runs skip it. Returns count."""
    if not scored:
        return 0
    conn = await _connect()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_jobs ("
            "  job_url TEXT PRIMARY KEY, verdict TEXT,"
            "  scored_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        rows = [(j.job_url, str(b)[:50]) for (b, j, _r) in scored]
        await conn.executemany(
            "INSERT INTO seen_jobs (job_url, verdict) VALUES ($1, $2) "
            "ON CONFLICT (job_url) DO NOTHING", rows
        )
        return len(rows)
    finally:
        await conn.close()


async def record_sent(jobs: list) -> int:
    """Insert the URLs we just emailed. jobs = list of (band, job, report). Returns count inserted."""
    if not jobs:
        return 0
    conn = await _connect()
    try:
        await conn.execute(DDL)
        rows = [(j.job_url, j.title, j.company) for (_b, j, _r) in jobs]
        result = await conn.executemany(
            "INSERT INTO digest_sent (job_url, title, company) VALUES ($1, $2, $3) "
            "ON CONFLICT (job_url) DO NOTHING",
            rows,
        )
        return len(rows)
    finally:
        await conn.close()