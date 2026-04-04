import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import settings

logger = logging.getLogger(__name__)


def _parse_url(url: str) -> tuple[str, dict]:
    # Normalize driver prefix to asyncpg.
    url = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", url)
    # asyncpg doesn't accept sslmode/ssl/channel_binding as URL params.
    # Strip them from the URL and return connect_args instead.
    needs_ssl = bool(re.search(r"sslmode=(require|verify-ca|verify-full|prefer|allow)", url))
    clean = re.sub(r"[?&](sslmode|ssl|channel_binding)=[^&]*", "", url)
    clean = re.sub(r"\?&", "?", clean).rstrip("?&")
    connect_args = {"ssl": "require"} if needs_ssl else {}
    return clean, connect_args


def _url_host(url: str) -> str:
    """Extract host:port from a DB URL for display purposes."""
    m = re.search(r"@([^/?]+)", url)
    return m.group(1) if m else "unknown"


def _runtime_database_url() -> str:
    return settings.database_private_url or settings.database_url


def _looks_like_public_railway_proxy(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("proxy.rlwy.net") or "tcp.proxy" in host


def _log_url_guidance(label: str, url: str) -> None:
    host = _url_host(url)
    if _looks_like_public_railway_proxy(url):
        logger.warning(
            "Database URL for %s uses a Railway public TCP proxy host (%s). "
            "Prefer DATABASE_PRIVATE_URL or another private Railway endpoint to reduce egress and latency.",
            label,
            host,
        )


def _build_engine(url: str, *, label: str = "runtime"):
    clean_url, connect_args = _parse_url(url)
    _log_url_guidance(label, url)
    if clean_url.startswith("postgresql"):
        # command_timeout: asyncpg cancels any single DB query taking >120s and
        # releases the connection cleanly (guards against runaway queries).
        connect_args = {**connect_args, "command_timeout": 120}
    eng = create_async_engine(
        clean_url,
        echo=False,
        connect_args=connect_args,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        pool_use_lifo=True,
        # Recycle connections before Railway/Neon proxy idle-timeout (~300s) kills them.
        # Expired connections are replaced transparently when next checked out.
        pool_recycle=280,
    )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    return eng, factory


engine, AsyncSessionLocal = _build_engine(_runtime_database_url())

# Active engine/factory — swappable at runtime (dev only)
_active_engine = engine
_active_session_factory = AsyncSessionLocal
_db_target: str = "local"
_schema_compat_checked = False
_schema_compat_lock = asyncio.Lock()
_RUNS_ERROR_SCHEMA_LOCK_KEY = 1_947_017_465
_RUNS_MODE_SCHEMA_LOCK_KEY = 1_947_017_466
_PROFILES_CANDIDATE_PROFILE_LOCK_KEY = 1_947_017_467
_JOBS_RAW_JOB_PROFILE_LOCK_KEY = 1_947_017_468
_JOB_RESULTS_REPORTS_LOCK_KEY = 1_947_017_469
_QUERY_PLAN_CACHE_LOCK_KEY = 1_947_017_470
_SCRAPE_QUERY_CACHE_LOCK_KEY = 1_947_017_471


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _active_session_factory() as session:
        await ensure_session_schema_compatibility(session)
        yield session


async def switch_database(target: str) -> None:
    global _active_engine, _active_session_factory, _db_target, _schema_compat_checked

    if target == "railway":
        url = settings.database_url_railway or settings.database_private_url
        if not url:
            raise ValueError("DATABASE_URL_RAILWAY or DATABASE_PRIVATE_URL is not configured")
    else:
        url = settings.database_url

    new_engine, new_factory = _build_engine(url, label=target)
    async with new_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    old_engine = _active_engine
    _active_engine = new_engine
    _active_session_factory = new_factory
    _db_target = target
    _schema_compat_checked = False

    await old_engine.dispose()


def get_db_info() -> dict:
    active_url = (
        (settings.database_url_railway or settings.database_private_url)
        if _db_target == "railway"
        else settings.database_url
    )
    return {
        "target": _db_target,
        "railway_available": bool(settings.database_url_railway or settings.database_private_url),
        "db_host": _url_host(active_url),
    }


async def ensure_runtime_schema_compatibility(bind=None) -> None:
    global _schema_compat_checked
    target = bind or _active_engine
    async with target.begin() as conn:
        checks = [
            ("runs", "error"),
            ("runs", "mode"),
            ("profiles", "candidate_profile"),
            ("jobs_raw", "job_profile"),
            ("job_results", "fit_band"),
            ("job_results", "confidence_band"),
            ("job_results", "explanation_summary"),
            ("job_results", "match_report"),
            ("job_results", "verification_report"),
            ("query_plan_cache", "cache_key"),
            ("scrape_query_cache", "provider"),
        ]
        existing = {
            (table_name, column_name)
            for table_name, column_name in (
                (
                    row[0],
                    row[1],
                )
                for row in (
                    await conn.execute(
                        text(
                            """
                            SELECT table_name, column_name
                            FROM information_schema.columns
                            WHERE table_schema = current_schema()
                              AND table_name IN ('runs', 'profiles', 'jobs_raw', 'job_results', 'query_plan_cache', 'scrape_query_cache')
                              AND column_name IN (
                                  'error', 'mode', 'candidate_profile', 'job_profile',
                                  'fit_band', 'confidence_band', 'explanation_summary',
                                  'match_report', 'verification_report',
                                  'cache_key', 'provider'
                              )
                            """
                        )
                    )
                ).all()
            )
        }

        missing = [item for item in checks if item not in existing]
        if not missing:
            if target is _active_engine:
                _schema_compat_checked = True
            return

        if conn.dialect.name == "postgresql":
            lock_map = {
                ("runs", "error"): _RUNS_ERROR_SCHEMA_LOCK_KEY,
                ("runs", "mode"): _RUNS_MODE_SCHEMA_LOCK_KEY,
                ("profiles", "candidate_profile"): _PROFILES_CANDIDATE_PROFILE_LOCK_KEY,
                ("jobs_raw", "job_profile"): _JOBS_RAW_JOB_PROFILE_LOCK_KEY,
                ("job_results", "fit_band"): _JOB_RESULTS_REPORTS_LOCK_KEY,
                ("job_results", "confidence_band"): _JOB_RESULTS_REPORTS_LOCK_KEY,
                ("job_results", "explanation_summary"): _JOB_RESULTS_REPORTS_LOCK_KEY,
                ("job_results", "match_report"): _JOB_RESULTS_REPORTS_LOCK_KEY,
                ("job_results", "verification_report"): _JOB_RESULTS_REPORTS_LOCK_KEY,
                ("query_plan_cache", "cache_key"): _QUERY_PLAN_CACHE_LOCK_KEY,
                ("scrape_query_cache", "provider"): _SCRAPE_QUERY_CACHE_LOCK_KEY,
            }
            for table_name, column_name in missing:
                lock_key = lock_map.get((table_name, column_name))
                if lock_key is not None:
                    await conn.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_key)"),
                        {"lock_key": lock_key},
                    )

        if ("runs", "error") in missing:
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT"))
        if ("runs", "mode") in missing:
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS mode VARCHAR(20)"))
            await conn.execute(
                text(
                    """
                    UPDATE runs
                    SET mode = COALESCE(NULLIF(progress->>'requested_mode', ''), 'quick')
                    WHERE mode IS NULL
                    """
                )
            )
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN mode SET DEFAULT 'quick'"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN mode SET NOT NULL"))
        if ("profiles", "candidate_profile") in missing:
            await conn.execute(text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS candidate_profile JSONB"))
        if ("jobs_raw", "job_profile") in missing:
            await conn.execute(text("ALTER TABLE jobs_raw ADD COLUMN IF NOT EXISTS job_profile JSONB"))
        if ("job_results", "fit_band") in missing:
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS fit_band VARCHAR(50)"))
        if ("job_results", "confidence_band") in missing:
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS confidence_band VARCHAR(50)"))
        if ("job_results", "explanation_summary") in missing:
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS explanation_summary TEXT"))
        if ("job_results", "match_report") in missing:
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS match_report JSONB"))
        if ("job_results", "verification_report") in missing:
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS verification_report JSONB"))
        if ("query_plan_cache", "cache_key") in missing:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS query_plan_cache (
                        id UUID PRIMARY KEY,
                        cache_key TEXT NOT NULL UNIQUE,
                        profile_fingerprint TEXT NOT NULL,
                        search_window_days INTEGER NOT NULL,
                        source_filter TEXT NOT NULL,
                        query_version VARCHAR(100) NOT NULL,
                        max_terms INTEGER NOT NULL,
                        query_payload JSONB DEFAULT '[]'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        updated_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_query_plan_cache_profile_window ON query_plan_cache (profile_fingerprint, search_window_days)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_query_plan_cache_source_filter ON query_plan_cache (source_filter)"
                )
            )
        if ("scrape_query_cache", "provider") in missing:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS scrape_query_cache (
                        id UUID PRIMARY KEY,
                        provider VARCHAR(50) NOT NULL,
                        site VARCHAR(50) NOT NULL,
                        term_normalized VARCHAR(255) NOT NULL,
                        location_normalized VARCHAR(255) NOT NULL DEFAULT '',
                        country_normalized VARCHAR(100) NOT NULL DEFAULT '',
                        hours_old INTEGER NOT NULL,
                        result_job_urls JSONB DEFAULT '[]'::jsonb,
                        result_count INTEGER NOT NULL DEFAULT 0,
                        searched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        fresh_until TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_scrape_query_cache_key
                    ON scrape_query_cache (provider, site, term_normalized, location_normalized, country_normalized, hours_old)
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_scrape_query_cache_fresh_until ON scrape_query_cache (provider, site, fresh_until)"
                )
            )
        if target is _active_engine:
            _schema_compat_checked = True


async def commit_with_runtime_schema_compatibility(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception as exc:
        if "UndefinedColumnError" not in str(exc) and "does not exist" not in str(exc):
            raise
        await ensure_runtime_schema_compatibility()
        await session.commit()


async def ensure_session_schema_compatibility(session: AsyncSession) -> None:
    global _schema_compat_checked
    if _schema_compat_checked:
        return
    async with _schema_compat_lock:
        if _schema_compat_checked:
            return
        await ensure_runtime_schema_compatibility(session.bind)
        _schema_compat_checked = True
