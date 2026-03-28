import math

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


async def test_store_sanitizes_non_finite_values(db: AsyncSession):
    """NaN and Inf in vectors must be replaced with 0.0 before insert."""
    cache = PgEmbeddingCache(db, cfg_fp="test-cfg-sanitize")
    vector = [float("nan"), float("inf"), float("-inf")] + [0.5] * 381
    # Should not raise; non-finite values are replaced with 0.0
    await cache.store_vectors([("fp-nan", vector)])
    result = await cache.fetch(["fp-nan"])
    assert "fp-nan" in result
    assert result["fp-nan"][0] == 0.0
    assert result["fp-nan"][1] == 0.0
    assert result["fp-nan"][2] == 0.0
    assert abs(result["fp-nan"][3] - 0.5) < 0.001


async def test_store_large_batch_across_chunk_boundary(db: AsyncSession):
    """Batch > 500 rows must be split and all rows stored."""
    cache = PgEmbeddingCache(db, cfg_fp="test-cfg-large")
    rows = [(f"fp-large-{i}", [float(i % 10) / 10] * 384) for i in range(520)]
    await cache.store_vectors(rows)
    fps = [r[0] for r in rows]
    result = await cache.fetch(fps)
    assert len(result) == 520


async def test_cfg_fp_isolation(db: AsyncSession):
    """Vectors stored under different cfg_fp must not be visible to each other."""
    cache_a = PgEmbeddingCache(db, cfg_fp="iso-cfg-A")
    cache_b = PgEmbeddingCache(db, cfg_fp="iso-cfg-B")
    await cache_a.store_vectors([("fp-shared", [0.1] * 384)])
    result = await cache_b.fetch(["fp-shared"])
    assert result == {}
