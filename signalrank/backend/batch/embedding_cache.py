import math
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Embedding, JobRaw

# Process-level LRU cache keyed by (cfg_fp, text_fp) — avoids re-fetching
# vectors from Neon on repeated ranking runs within the same process lifetime.
_VECTOR_CACHE: dict[tuple[str, str], list[float]] = {}
_VECTOR_CACHE_MAX = 20_000


def _clean_vector(vector: Sequence[float]) -> list[float]:
    return [v if math.isfinite(v) else 0.0 for v in vector]


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
                if len(_VECTOR_CACHE) < _VECTOR_CACHE_MAX:
                    _VECTOR_CACHE[(self.cfg_fp, row.text_fp)] = vec
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
                pg_insert(Embedding)
                .values(values)
                .on_conflict_do_nothing(index_elements=["text_fp", "cfg_fp"])
            )
            for text_fp, vector in batch:
                key = (self.cfg_fp, text_fp)
                if key not in _VECTOR_CACHE and len(_VECTOR_CACHE) < _VECTOR_CACHE_MAX:
                    _VECTOR_CACHE[key] = _clean_vector(vector)
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
        insert_stmt = pg_insert(JobRaw).values(values)
        await db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=["job_url"],
                set_={"embedding": insert_stmt.excluded.embedding},
            )
        )
    await db.flush()
