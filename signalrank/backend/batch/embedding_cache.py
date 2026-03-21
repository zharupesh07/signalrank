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
        result = await self.db.execute(
            select(Embedding.text_fp, Embedding.vector).where(
                Embedding.text_fp.in_(list(text_fps)),
                Embedding.cfg_fp == self.cfg_fp,
            )
        )
        return {row.text_fp: list(row.vector) for row in result.all()}

    async def store_vectors(self, rows: list[tuple[str, list[float]]]) -> None:
        if not rows:
            return
        for text_fp, vector in rows:
            vector_str = "[" + ",".join(str(v) for v in vector) + "]"
            stmt = text(
                f"INSERT INTO embeddings (id, text_fp, cfg_fp, vector) "
                f"VALUES (gen_random_uuid(), :text_fp, :cfg_fp, '{vector_str}'::vector) "
                f"ON CONFLICT (text_fp, cfg_fp) DO NOTHING"
            )
            await self.db.execute(
                stmt,
                {"text_fp": text_fp, "cfg_fp": self.cfg_fp},
            )
        await self.db.flush()
