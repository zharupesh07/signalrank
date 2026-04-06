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


async def test_ensure_runtime_schema_compatibility_adds_run_claim_columns(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS claimed_by"))
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS claim_token"))
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS lease_expires_at"))
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS last_heartbeat_at"))
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS attempt_count"))
        await conn.execute(text("ALTER TABLE runs DROP COLUMN IF EXISTS cancel_requested"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'runs'
                  AND column_name IN (
                    'claimed_by',
                    'claim_token',
                    'lease_expires_at',
                    'last_heartbeat_at',
                    'attempt_count',
                    'cancel_requested'
                  )
                ORDER BY column_name
                """
            )
        )
        assert result.scalars().all() == [
            "attempt_count",
            "cancel_requested",
            "claim_token",
            "claimed_by",
            "last_heartbeat_at",
            "lease_expires_at",
        ]


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


async def test_ensure_runtime_schema_compatibility_adds_query_plan_cache_table(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS query_plan_cache"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name = 'query_plan_cache'
                """
            )
        )
        assert result.scalar_one() == "query_plan_cache"


async def test_ensure_runtime_schema_compatibility_adds_scrape_query_cache_table(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS scrape_query_cache"))

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name = 'scrape_query_cache'
                """
            )
        )
        assert result.scalar_one() == "scrape_query_cache"


async def test_ensure_runtime_schema_compatibility_adds_scrape_query_cache_constraint_to_index_only_table(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS scrape_query_cache"))
        await conn.execute(
            text(
                """
                CREATE TABLE scrape_query_cache (
                    id UUID PRIMARY KEY,
                    provider VARCHAR(50) NOT NULL,
                    site VARCHAR(50) NOT NULL,
                    term_normalized VARCHAR(255) NOT NULL,
                    location_normalized VARCHAR(255) NOT NULL DEFAULT '',
                    country_normalized VARCHAR(100) NOT NULL DEFAULT '',
                    hours_old INTEGER NOT NULL,
                    result_job_urls JSONB DEFAULT '[]'::jsonb,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    searched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    fresh_until TIMESTAMPTZ NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_scrape_query_cache_key
                ON scrape_query_cache (provider, site, term_normalized, location_normalized, country_normalized, hours_old)
                """
            )
        )

    await ensure_runtime_schema_compatibility(test_engine)

    async with test_engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = 'scrape_query_cache'
                  AND constraint_name = 'uq_scrape_query_cache_key'
                """
            )
        )
        assert result.scalar_one() == "uq_scrape_query_cache_key"
