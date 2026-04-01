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
        error_exists = (
            await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'runs'
                      AND column_name = 'error'
                    """
                )
            )
        ).scalar() == 1
        mode_exists = (
            await conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'runs'
                      AND column_name = 'mode'
                    """
                )
            )
        ).scalar() == 1
        if error_exists and mode_exists:
            if target is _active_engine:
                _schema_compat_checked = True
            return
        if conn.dialect.name == "postgresql":
            if not error_exists:
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _RUNS_ERROR_SCHEMA_LOCK_KEY},
                )
                error_exists = (
                    await conn.execute(
                        text(
                            """
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = current_schema()
                              AND table_name = 'runs'
                              AND column_name = 'error'
                            """
                        )
                    )
                ).scalar() == 1
            if not mode_exists:
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _RUNS_MODE_SCHEMA_LOCK_KEY},
                )
                mode_exists = (
                    await conn.execute(
                        text(
                            """
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = current_schema()
                              AND table_name = 'runs'
                              AND column_name = 'mode'
                            """
                        )
                    )
                ).scalar() == 1
        if not error_exists:
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT"))
        if not mode_exists:
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
    if target is _active_engine:
        _schema_compat_checked = True


async def ensure_session_schema_compatibility(session: AsyncSession) -> None:
    global _schema_compat_checked
    if _schema_compat_checked:
        return
    async with _schema_compat_lock:
        if _schema_compat_checked:
            return
        await ensure_runtime_schema_compatibility(session.bind)
        _schema_compat_checked = True
