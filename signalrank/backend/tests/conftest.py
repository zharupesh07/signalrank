import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import llm.openrouter as _openrouter_mod

from api.database import Base, get_db
from api.main import app, limiter as app_limiter
from api.routes.auth import _limiter as auth_limiter

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank_test"


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """Create DB schema once per session synchronously — avoids event-loop sharing issues."""
    async def _create():
        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("DROP TABLE IF EXISTS query_plan_cache CASCADE"))
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS candidate_profile JSONB"))
            await conn.execute(text("ALTER TABLE jobs_raw ADD COLUMN IF NOT EXISTS job_profile JSONB"))
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS fit_band VARCHAR(50)"))
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS confidence_band VARCHAR(50)"))
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS explanation_summary TEXT"))
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS match_report JSONB"))
            await conn.execute(text("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS verification_report JSONB"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS mode VARCHAR(20)"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS claim_token VARCHAR(64)"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS attempt_count INTEGER"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(50)"))
            await conn.execute(text("ALTER TABLE runs ADD COLUMN IF NOT EXISTS executor_type VARCHAR(50)"))
            await conn.execute(
                text(
                    """
                    UPDATE runs
                    SET mode = COALESCE(NULLIF(progress->>'requested_mode', ''), 'quick')
                    WHERE mode IS NULL
                    """
                )
            )
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN mode SET DEFAULT 'quick'"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN mode SET NOT NULL"))
            await conn.execute(text("UPDATE runs SET attempt_count = 0 WHERE attempt_count IS NULL"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN attempt_count SET DEFAULT 0"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN attempt_count SET NOT NULL"))
            await conn.execute(text("UPDATE runs SET cancel_requested = false WHERE cancel_requested IS NULL"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN cancel_requested SET DEFAULT false"))
            await conn.execute(text("ALTER TABLE runs ALTER COLUMN cancel_requested SET NOT NULL"))
        await engine.dispose()

    asyncio.run(_create())


@pytest.fixture
async def test_engine():
    """Per-test engine: truncate all tables for isolation, then yield."""
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def clear_caches():
    _openrouter_mod._response_cache.clear()
    # Reset rate limiter storage to prevent cross-test 429s
    app_limiter.reset()
    auth_limiter.reset()
    yield
    _openrouter_mod._response_cache.clear()


@pytest.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
