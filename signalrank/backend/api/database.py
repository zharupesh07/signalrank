import asyncio
import re
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import settings


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


def _build_engine(url: str):
    clean_url, connect_args = _parse_url(url)
    eng = create_async_engine(
        clean_url,
        echo=False,
        connect_args=connect_args,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        pool_use_lifo=True,
    )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    return eng, factory


engine, AsyncSessionLocal = _build_engine(settings.database_url)

# Active engine/factory — swappable at runtime (dev only)
_active_engine = engine
_active_session_factory = AsyncSessionLocal
_db_target: str = "local"
_schema_compat_checked = False
_schema_compat_lock = asyncio.Lock()


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _active_session_factory() as session:
        await ensure_session_schema_compatibility(session)
        yield session


async def switch_database(target: str) -> None:
    global _active_engine, _active_session_factory, _db_target, _schema_compat_checked

    if target == "railway":
        if not settings.database_url_railway:
            raise ValueError("DATABASE_URL_RAILWAY is not configured")
        url = settings.database_url_railway
    else:
        url = settings.database_url

    new_engine, new_factory = _build_engine(url)
    async with new_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    old_engine = _active_engine
    _active_engine = new_engine
    _active_session_factory = new_factory
    _db_target = target
    _schema_compat_checked = False

    await old_engine.dispose()


def get_db_info() -> dict:
    return {
        "target": _db_target,
        "railway_available": bool(settings.database_url_railway),
        "db_host": _url_host(
            settings.database_url_railway if _db_target == "railway" else settings.database_url
        ),
    }


async def ensure_runtime_schema_compatibility(bind=None) -> None:
    target = bind or _active_engine
    async with target.begin() as conn:
        await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT"))


async def ensure_session_schema_compatibility(session: AsyncSession) -> None:
    global _schema_compat_checked
    if _schema_compat_checked:
        return
    async with _schema_compat_lock:
        if _schema_compat_checked:
            return
        await ensure_runtime_schema_compatibility(session.bind)
        _schema_compat_checked = True
