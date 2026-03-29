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


_db_url, _connect_args = _parse_url(settings.database_url)
engine = create_async_engine(
    _db_url,
    echo=False,
    connect_args=_connect_args,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    pool_use_lifo=True,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def ensure_runtime_schema_compatibility(bind=None) -> None:
    target = bind or engine
    async with target.begin() as conn:
        await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT"))
