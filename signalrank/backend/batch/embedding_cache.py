import math
import os
from collections.abc import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Embedding, JobRaw
from api.sql_compat import dialect_insert
from batch.context import load_base_config

# Process-level LRU cache keyed by (cfg_fp, text_fp) — avoids re-fetching
# vectors from Neon on repeated ranking runs within the same process lifetime.
# Values are float32 ndarrays (~1.5KB each) instead of Python list[float] (~9.2KB each).
_VECTOR_CACHE: dict[tuple[str, str], np.ndarray] = {}
_VECTOR_CACHE_MAX = int(os.getenv("VECTOR_CACHE_MAX", load_base_config().get("caching", {}).get("vector_cache_max", 2_000)))


def _clean_vector(vector: Sequence[float]) -> list[float]:
    return [v if math.isfinite(v) else 0.0 for v in vector]


def _remember_vector(key: tuple[str, str], vector: Sequence[float]) -> None:
    if _VECTOR_CACHE_MAX <= 0:
        return
    if key in _VECTOR_CACHE:
        return
    if len(_VECTOR_CACHE) >= _VECTOR_CACHE_MAX:
        _VECTOR_CACHE.pop(next(iter(_VECTOR_CACHE)))
    arr = np.array(vector, dtype="float32")
    arr[~np.isfinite(arr)] = 0.0
    _VECTOR_CACHE[key] = arr


def clear_vector_cache() -> None:
    _VECTOR_CACHE.clear()


class PgEmbeddingCache:
    def __init__(self, db: AsyncSession, cfg_fp: str):
        self.db = db
        self.cfg_fp = cfg_fp

    async def fetch(self, text_fps: Sequence[str]) -> dict[str, list[float]]:
        if not text_fps:
            return {}
        out: dict[str, list[float]] = {}
        missing: list[str] = []
        for fp in text_fps:
            cached = _VECTOR_CACHE.get((self.cfg_fp, fp))
            if cached is not None:
                out[fp] = cached
            else:
                missing.append(fp)

        batch_size = 5000
        for i in range(0, len(missing), batch_size):
            batch = missing[i:i + batch_size]
            result = await self.db.execute(
                select(Embedding.text_fp, Embedding.vector).where(
                    Embedding.text_fp.in_(batch),
                    Embedding.cfg_fp == self.cfg_fp,
                )
            )
            for row in result.all():
                vec = list(row.vector)
                out[row.text_fp] = vec
                _remember_vector((self.cfg_fp, row.text_fp), vec)
        return out

    async def store_vectors(self, rows: list[tuple[str, list[float]]]) -> None:
        if not rows:
            return
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            values = []
            for text_fp, vector in batch:
                clean = _clean_vector(vector)
                values.append({"text_fp": text_fp, "cfg_fp": self.cfg_fp, "vector": clean})
            await self.db.execute(
                dialect_insert(self.db, Embedding)
                .values(values)
                .on_conflict_do_nothing(index_elements=["text_fp", "cfg_fp"])
            )
            for text_fp, vector in batch:
                _remember_vector((self.cfg_fp, text_fp), vector)
        await self.db.flush()


async def store_job_embeddings(
    db: AsyncSession,
    rows: list[tuple[str, list[float]]],
) -> None:
    if not rows:
        return
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        values = [
            {"job_url": job_url, "embedding": _clean_vector(vector)}
            for job_url, vector in batch
        ]
        insert_stmt = dialect_insert(db, JobRaw).values(values)
        await db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["job_url"],
                set_={"embedding": insert_stmt.excluded.embedding},
            )
        )
    await db.flush()
