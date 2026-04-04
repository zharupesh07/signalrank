from sqlalchemy import event, text

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


async def test_ensure_runtime_schema_compatibility_adds_candidate_profile_column(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE profiles DROP COLUMN IF EXISTS candidate_profile"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'profiles' AND column_name = 'candidate_profile'
                """
            )
        )
        assert result.scalar_one() == "candidate_profile"


async def test_ensure_runtime_schema_compatibility_adds_job_results_reports_columns(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE job_results DROP COLUMN IF EXISTS fit_band"))
        await conn.execute(text("ALTER TABLE job_results DROP COLUMN IF EXISTS confidence_band"))
        await conn.execute(text("ALTER TABLE job_results DROP COLUMN IF EXISTS explanation_summary"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'job_results'
                  AND column_name IN ('fit_band', 'confidence_band', 'explanation_summary')
                ORDER BY column_name
                """
            )
        )
        assert result.scalars().all() == ["confidence_band", "explanation_summary", "fit_band"]


async def test_get_db_session_compatibility_repairs_runs_error_column(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS error"))

    original_session_local = database.AsyncSessionLocal
    original_active_factory = database._active_session_factory
    original_active_engine = database._active_engine
    original_checked = database._schema_compat_checked
    session_factory = database.async_sessionmaker(test_engine, expire_on_commit=False)
    database.AsyncSessionLocal = session_factory
    database._active_session_factory = session_factory
    database._active_engine = test_engine
    database._schema_compat_checked = False

    try:
        async for session in database.get_db():
            await database.ensure_session_schema_compatibility(session)
            break
    finally:
        database.AsyncSessionLocal = original_session_local
        database._active_session_factory = original_active_factory
        database._active_engine = original_active_engine
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


async def test_ensure_runtime_schema_compatibility_skips_alter_when_runs_error_column_exists(test_engine):
    statements: list[str] = []

    def _capture_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _capture_sql)
    try:
        await ensure_runtime_schema_compatibility(test_engine)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capture_sql)

    assert any("information_schema.columns" in statement for statement in statements)
    assert not any("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT" in statement for statement in statements)
