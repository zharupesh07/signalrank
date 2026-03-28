import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import settings


def _parse_url(url: str) -> tuple[str, dict]:
    # asyncpg doesn't accept sslmode/ssl/channel_binding as URL params.
    # Strip them from the URL and return connect_args instead.
    needs_ssl = bool(re.search(r"sslmode=(require|verify-ca|verify-full|prefer|allow)", url))
    clean = re.sub(r"[?&](sslmode|ssl|channel_binding)=[^&]*", "", url)
    clean = re.sub(r"\?&", "?", clean).rstrip("?&")
    connect_args = {"ssl": True} if needs_ssl else {}
    return clean, connect_args


_db_url, _connect_args = _parse_url(settings.database_url)
engine = create_async_engine(
    _db_url,
    echo=False,
    connect_args=_connect_args,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
