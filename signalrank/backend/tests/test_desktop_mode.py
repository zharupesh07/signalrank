import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlite_schema_can_be_created(tmp_path):
    from api.database import Base
    import api.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        tables = (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        ).scalars().all()
    await engine.dispose()

    assert "users" in tables
    assert "profiles" in tables
    assert "jobs_raw" in tables
    assert "embeddings" in tables


@pytest.mark.asyncio
async def test_sqlite_worker_claims_pending_run_with_server_default_timestamp(tmp_path):
    from api.database import Base
    from api.models import Run, User
    from batch.worker import _claim_pending_run
    import api.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "insert into users (id, email, password_hash, provider, is_admin) "
                "values ('user-1', 'worker@test.local', 'x', 'credentials', 1)"
            )
        )
        await conn.execute(
            text(
                "insert into runs (id, user_id, status, mode) "
                "values ('run-1', 'user-1', 'pending', 'quick')"
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        claimed = await _claim_pending_run(session_factory, "quick")
        assert claimed is not None
        assert claimed.run_id == "run-1"

        async with session_factory() as db:
            run = (await db.execute(select(Run).where(Run.id == "run-1"))).scalar_one()
            assert run.status == "claimed"
            assert run.claim_token == claimed.claim_token
    finally:
        await engine.dispose()


async def _sqlite_client(tmp_path, monkeypatch):
    from api.config import settings
    from api.database import Base, get_db
    from api.main import app
    import api.models  # noqa: F401

    monkeypatch.setattr(settings, "signalrank_mode", "desktop")
    monkeypatch.setattr(settings, "signalrank_app_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return app, get_db, engine, session_factory, client


@pytest.mark.asyncio
async def test_desktop_status_creates_local_user(tmp_path, monkeypatch):
    from api.models import User

    app, get_db, engine, session_factory, client = await _sqlite_client(tmp_path, monkeypatch)

    try:
        res = await client.get("/api/desktop/status")
        assert res.status_code == 200
        assert res.json()["mode"] == "desktop"

        async with session_factory() as db:
            user = (
                await db.execute(select(User).where(User.email == "local@signalrank.desktop"))
            ).scalar_one_or_none()
            assert user is not None
            assert user.is_admin is True
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_key_is_validated_and_saved(tmp_path, monkeypatch):
    from api.config import settings
    from api.routes import desktop

    app, get_db, engine, _, client = await _sqlite_client(tmp_path, monkeypatch)
    monkeypatch.setattr(desktop, "_save_keychain_key", lambda provider, key: False)
    monkeypatch.setattr(desktop, "_load_keychain_key", lambda provider: "")

    class FakeClient:
        def __init__(self, *, provider, api_key, timeout):
            self.provider = provider
            self.api_key = api_key
            self.timeout = timeout

        async def probe_models(self, limit=1):
            return ["test-model"]

    monkeypatch.setattr(
        desktop,
        "build_llm_client",
        lambda *, provider, api_key, timeout: FakeClient(
            provider=provider,
            api_key=api_key,
            timeout=timeout,
        ),
    )

    try:
        res = await client.post(
            "/api/desktop/provider-key",
            json={"provider": "openai", "api_key": "sk-test"},
        )
        assert res.status_code == 200
        assert res.json()["provider"] == "openai"
        assert settings.openai_api_key == "sk-test"
        assert settings.llm_provider == "openai"
        assert (tmp_path / "provider.json").exists()
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_ann_prefilter_uses_python_similarity(tmp_path):
    from datetime import datetime, timezone

    from api.database import Base
    from api.models import JobRaw
    from batch.ranker import ann_prefilter_job_urls

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        db.add_all(
            [
                JobRaw(
                    job_url="https://jobs.example/close",
                    title="Close",
                    embedding=[1.0, 0.0, 0.0],
                    ingested_at=datetime.now(timezone.utc),
                ),
                JobRaw(
                    job_url="https://jobs.example/far",
                    title="Far",
                    embedding=[0.0, 1.0, 0.0],
                    ingested_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db.commit()

        urls = await ann_prefilter_job_urls(db, [1.0, 0.0, 0.0], limit=2)

    await engine.dispose()
    assert urls == ["https://jobs.example/close", "https://jobs.example/far"]


@pytest.mark.asyncio
async def test_sqlite_v4_load_jobs_uses_substr_for_description(tmp_path):
    from datetime import datetime, timezone

    from api.database import Base
    from api.models import JobRaw
    from ranking.v4.db_scorer import _RANK_DESCRIPTION_CHARS, _load_jobs

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    full_description = "x" * (_RANK_DESCRIPTION_CHARS + 25)
    async with session_factory() as db:
        db.add(
            JobRaw(
                job_url="https://jobs.example/v4",
                title="Platform Engineer",
                company="Acme",
                description=full_description,
                ingested_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        jobs = await _load_jobs(db, ["https://jobs.example/v4"], None)

    await engine.dispose()
    assert len(jobs) == 1
    assert jobs[0]["description"] == full_description[:_RANK_DESCRIPTION_CHARS]


@pytest.mark.asyncio
async def test_sqlite_legacy_ranker_loads_jobs_with_substr(tmp_path):
    from datetime import datetime, timezone

    from api.database import Base
    from api.models import JobRaw
    from batch.ranker import _RANK_DESCRIPTION_CHARS, load_jobs_dataframe

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'signalrank.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    full_description = "y" * (_RANK_DESCRIPTION_CHARS + 25)
    async with session_factory() as db:
        db.add(
            JobRaw(
                job_url="https://jobs.example/legacy",
                title="ML Engineer",
                company="Beta",
                description=full_description,
                ingested_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        df = await load_jobs_dataframe(
            db,
            job_urls=["https://jobs.example/legacy"],
        )

    await engine.dispose()
    assert len(df) == 1
    assert df.iloc[0]["description"] == full_description[:_RANK_DESCRIPTION_CHARS]


@pytest.mark.asyncio
async def test_desktop_session_returns_token(tmp_path, monkeypatch):
    from api.auth import decode_token

    app, get_db, engine, _, client = await _sqlite_client(tmp_path, monkeypatch)

    try:
        res = await client.post("/api/desktop/session")
        assert res.status_code == 200

        payload = decode_token(res.json()["access_token"])
        assert payload["email"] == "local@signalrank.desktop"
        assert payload["is_admin"] is True
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_desktop_session_is_idempotent_under_concurrent_first_run(
    tmp_path, monkeypatch
):
    from api.models import User

    app, get_db, engine, session_factory, client = await _sqlite_client(
        tmp_path, monkeypatch
    )

    try:
        responses = await asyncio.gather(
            *(client.post("/api/desktop/session") for _ in range(5))
        )
        assert all(response.status_code == 200 for response in responses)

        async with session_factory() as db:
            users = (
                await db.execute(
                    select(User).where(User.email == "local@signalrank.desktop")
                )
            ).scalars().all()
            assert len(users) == 1
    finally:
        await client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
