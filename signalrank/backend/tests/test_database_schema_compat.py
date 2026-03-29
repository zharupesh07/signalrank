from sqlalchemy import text

import api.database as database
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


async def test_get_db_session_compatibility_repairs_runs_error_column(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS error"))

    original_session_local = database.AsyncSessionLocal
    original_checked = database._schema_compat_checked
    session_factory = database.async_sessionmaker(test_engine, expire_on_commit=False)
    database.AsyncSessionLocal = session_factory
    database._schema_compat_checked = False

    try:
        async for session in database.get_db():
            await database.ensure_session_schema_compatibility(session)
            break
    finally:
        database.AsyncSessionLocal = original_session_local
        database._schema_compat_checked = original_checked

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
