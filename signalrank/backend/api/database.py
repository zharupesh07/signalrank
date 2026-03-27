from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import settings


def _make_engine_url(url: str) -> str:
    # asyncpg doesn't support sslmode= query param; convert to ssl=true
    url = url.replace("sslmode=require", "ssl=true")
    url = url.replace("sslmode=prefer", "ssl=true")
    url = url.replace("&&", "&").strip("?&")
    return url


engine = create_async_engine(_make_engine_url(settings.database_url), echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
