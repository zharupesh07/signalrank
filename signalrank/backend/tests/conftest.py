import asyncio
import os
import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import llm.openrouter as _openrouter_mod

from api.database import Base

DEFAULT_TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank_test"
TEST_DB_URL = os.getenv("SIGNALRANK_TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)


def _worker_test_db_url() -> str:
    worker_id = os.getenv("PYTEST_XDIST_WORKER")
    if not worker_id:
        return TEST_DB_URL

    url = make_url(TEST_DB_URL)
    database = url.database or "signalrank_test"
    return url.set(database=f"{database}_{worker_id}").render_as_string(hide_password=False)


async def _ensure_database_exists(db_url: str):
    url = make_url(db_url)
    database = url.database
    if not database or not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise RuntimeError(f"Unsafe test database name: {database!r}")

    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as conn:
        exists = (
            await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": database},
            )
        ).scalar_one_or_none()
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{database}"'))
    await engine.dispose()


@pytest.fixture(scope="session")
def _ensure_schema():
    async def _create():
        db_url = _worker_test_db_url()
        await _ensure_database_exists(db_url)
        engine = create_async_engine(db_url)
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
async def test_engine(_ensure_schema):
    engine = create_async_engine(_worker_test_db_url())
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
def clear_caches(request):
    _openrouter_mod._response_cache.clear()
    if "client" in request.fixturenames:
        from api.main import limiter as app_limiter
        from api.routes.auth import _limiter as auth_limiter

        app_limiter.reset()
        auth_limiter.reset()
    yield
    _openrouter_mod._response_cache.clear()


@pytest.fixture
async def client(db: AsyncSession):
    from api.database import get_db
    from api.main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
