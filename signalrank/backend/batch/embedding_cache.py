from collections.abc import Sequence

from sqlalchemy import select, text
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
            values_parts = []
            params = {"cfg_fp": self.cfg_fp}
            for j, (text_fp, vector) in enumerate(batch):
                vector_str = "[" + ",".join(str(v) for v in vector) + "]"
                values_parts.append(
                    f"(gen_random_uuid(), :fp_{j}, :cfg_fp, '{vector_str}'::vector)"
                )
                params[f"fp_{j}"] = text_fp
            sql = (
                f"INSERT INTO embeddings (id, text_fp, cfg_fp, vector) VALUES "
                f"{', '.join(values_parts)} ON CONFLICT (text_fp, cfg_fp) DO NOTHING"
            )
            await self.db.execute(text(sql), params)
        await self.db.flush()
