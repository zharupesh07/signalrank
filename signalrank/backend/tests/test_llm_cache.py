from sqlalchemy.ext.asyncio import AsyncSession

from llm.cache import PromptCache


async def test_cache_miss_returns_none(db: AsyncSession):
    cache = PromptCache(db)
    result = await cache.get("nonexistent-hash")
    assert result is None


async def test_cache_set_and_get(db: AsyncSession):
    cache = PromptCache(db)
    await cache.set("test-hash-1", {"result": "cached"})
    result = await cache.get("test-hash-1")
    assert result == {"result": "cached"}


async def test_cache_expired_returns_none(db: AsyncSession):
    cache = PromptCache(db, ttl_seconds=0)
    await cache.set("test-hash-expired", {"old": True})
    result = await cache.get("test-hash-expired")
    assert result is None
