from sqlalchemy import text

from api.database import ensure_runtime_schema_compatibility


async def test_ensure_runtime_schema_compatibility_adds_runs_error_column(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS error"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'runs' AND column_name = 'error'
                """
            )
        )
        assert result.scalar_one() == "error"
