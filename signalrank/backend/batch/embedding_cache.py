import math
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Embedding


class PgEmbeddingCache:
    def __init__(self, db: AsyncSession, cfg_fp: str):
        self.db = db
        self.cfg_fp = cfg_fp

    async def fetch(self, text_fps: Sequence[str]) -> dict[str, list[float]]:
        if not text_fps:
            return {}
        out: dict[str, list[float]] = {}
        batch_size = 5000
        fps_list = list(text_fps)
        for i in range(0, len(fps_list), batch_size):
            batch = fps_list[i:i + batch_size]
            result = await self.db.execute(
                select(Embedding.text_fp, Embedding.vector).where(
                    Embedding.text_fp.in_(batch),
                    Embedding.cfg_fp == self.cfg_fp,
                )
            )
            for row in result.all():
                out[row.text_fp] = list(row.vector)
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
        await self.db.flush()
