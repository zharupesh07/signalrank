import hashlib
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import LLMCache

CACHE_TTL = 86400


def prompt_hash(prompt: str) -> str:
    return hashlib.md5(prompt.encode()).hexdigest()


class PromptCache:
    def __init__(self, db: AsyncSession, ttl_seconds: int = CACHE_TTL):
        self.db = db
        self.ttl = ttl_seconds

    async def get(self, hash_key: str) -> dict | None:
        result = await self.db.execute(
            select(LLMCache).where(LLMCache.prompt_hash == hash_key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        age = (datetime.now(timezone.utc) - row.created_at.replace(tzinfo=timezone.utc)).total_seconds()
        if age > self.ttl:
            return None

        return row.response_json

    async def set(self, hash_key: str, response: dict) -> None:
        await self.db.execute(
            delete(LLMCache).where(LLMCache.prompt_hash == hash_key)
        )
        self.db.add(LLMCache(prompt_hash=hash_key, response_json=response))
        await self.db.flush()
