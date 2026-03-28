import math
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Embedding

# Process-level LRU cache keyed by (cfg_fp, text_fp) — avoids re-fetching
# vectors from Neon on repeated ranking runs within the same process lifetime.
_VECTOR_CACHE: dict[tuple[str, str], list[float]] = {}
_VECTOR_CACHE_MAX = 20_000


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
                # Sanitize: replace non-finite floats to avoid DB errors
                clean = [v if math.isfinite(v) else 0.0 for v in vector]
                values.append({"text_fp": text_fp, "cfg_fp": self.cfg_fp, "vector": clean})
            await self.db.execute(
                pg_insert(Embedding)
                .values(values)
                .on_conflict_do_nothing(index_elements=["text_fp", "cfg_fp"])
            )
            for text_fp, vector in batch:
                if len(_VECTOR_CACHE) < _VECTOR_CACHE_MAX:
                    clean = [v if math.isfinite(v) else 0.0 for v in vector]
                    _VECTOR_CACHE[(self.cfg_fp, text_fp)] = clean
        await self.db.flush()
