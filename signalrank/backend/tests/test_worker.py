from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import Profile, Run, User
from batch.worker import process_run


class _EmptyRankedDf:
    def __len__(self):
        return 0

    def to_dict(self, orient):
        assert orient == "records"
        return []


@pytest.mark.asyncio
async def test_process_run_full_mode_ignores_multiple_recent_successful_scrapes(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="Backend engineer",
        scraper_hours_old=168,
        scraper_max_terms=3,
    )
    db.add(profile)

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            Run(
                user_id=user.id,
                status="success",
                scrape_count=25,
                finished_at=now - timedelta(hours=2),
            ),
            Run(
                user_id=user.id,
                status="success",
                scrape_count=18,
                finished_at=now - timedelta(hours=4),
            ),
        ]
    )

    current_run = Run(user_id=user.id, status="pending")
    db.add(current_run)
    await db.commit()

    import batch.query_builder as query_builder
    import batch.ranker as ranker

    monkeypatch.setattr(query_builder, "build_queries", lambda profile, max_terms=None: [])

    async def _score_jobs_for_user(**kwargs):
        return _EmptyRankedDf()

    monkeypatch.setattr(ranker, "score_jobs_for_user", _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(current_run.id, user.id, session_factory, mode="full")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert refreshed_run.job_count == 0


@pytest.mark.asyncio
async def test_process_run_persists_error_message_on_failure(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-error@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="Backend engineer",
        scraper_hours_old=24,
        scraper_max_terms=1,
    )
    db.add(profile)

    current_run = Run(user_id=user.id, status="pending")
    db.add(current_run)
    await db.commit()

    import batch.query_builder as query_builder

    def _boom(profile, max_terms=None):
        raise ValueError("query builder exploded")

    monkeypatch.setattr(query_builder, "build_queries", _boom)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(current_run.id, user.id, session_factory, mode="quick")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert refreshed_run.status == "failed"
    assert refreshed_run.error == "ValueError: query builder exploded"
