from sqlalchemy.ext.asyncio import AsyncSession

from batch.embedding_cache import PgEmbeddingCache


async def test_fetch_empty(db: AsyncSession):
    cache = PgEmbeddingCache(db, cfg_fp="test-cfg")
    result = await cache.fetch(["nonexistent-fp"])
    assert result == {}


async def test_store_and_fetch(db: AsyncSession):
    cache = PgEmbeddingCache(db, cfg_fp="test-cfg-123")
    vector = [0.1] * 384
    await cache.store_vectors([("fp-abc", vector)])
    result = await cache.fetch(["fp-abc"])
    assert "fp-abc" in result
    assert len(result["fp-abc"]) == 384
    assert abs(result["fp-abc"][0] - 0.1) < 0.001


async def test_store_duplicate_is_noop(db: AsyncSession):
    cache = PgEmbeddingCache(db, cfg_fp="test-cfg-dup")
    vector = [0.2] * 384
    await cache.store_vectors([("fp-dup", vector)])
    await cache.store_vectors([("fp-dup", [0.9] * 384)])
    result = await cache.fetch(["fp-dup"])
    assert abs(result["fp-dup"][0] - 0.2) < 0.001
