from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import Profile, Run, User
from batch.query_builder import SearchQuery
from batch.worker import _claim_pending_run, process_run


def _empty_ranked_df():
    return pd.DataFrame(columns=["id", "final_score", "semantic_score", "skills_score",
                                  "company_score", "seniority_score_dim", "location_score",
                                  "recency_score", "company_tier", "is_contract"])


@pytest.mark.asyncio
async def test_process_run_full_mode_manual_run_does_not_skip_scrape_after_recent_deep_scan(
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
                mode="full",
                scrape_count=25,
                finished_at=now - timedelta(hours=2),
                progress={"requested_mode": "full", "force_scrape": False, "scrape_executed": True},
            ),
            Run(
                user_id=user.id,
                status="success",
                mode="quick",
                scrape_count=18,
                finished_at=now - timedelta(hours=4),
                progress={"requested_mode": "quick", "force_scrape": False, "scrape_executed": True},
            ),
        ]
    )

    current_run = Run(user_id=user.id, status="pending", mode="full")
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.ranker as ranker

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="Backend Engineer", location="", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    scrape_calls = 0

    async def _scrape(*args, **kwargs):
        nonlocal scrape_calls
        scrape_calls += 1
        return []

    monkeypatch.setattr(scraper, "scrape", _scrape)

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

    monkeypatch.setattr(ranker, "score_jobs_for_user", _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(current_run.id, user.id, session_factory, mode="full")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert scrape_calls == 1
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert refreshed_run.job_count == 0
    assert refreshed_run.progress["requested_mode"] == "full"
    assert refreshed_run.progress["force_scrape"] is False
    assert refreshed_run.progress["disable_scraping"] is False
    assert refreshed_run.progress["scrape_executed"] is True


@pytest.mark.asyncio
async def test_process_run_full_mode_auto_refresh_skips_scrape_after_recent_deep_scan(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-auto@test.com", password_hash="mock", provider="credentials")
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
    db.add(
        Run(
            user_id=user.id,
            status="success",
            mode="full",
            scrape_count=25,
            finished_at=now - timedelta(hours=2),
            progress={"requested_mode": "full", "force_scrape": False, "scrape_executed": True},
        )
    )

    current_run = Run(
        user_id=user.id,
        status="pending",
        mode="full",
        progress={"requested_mode": "full", "force_scrape": False, "disable_scraping": False, "auto_refresh": True},
    )
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.ranker as ranker

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="Backend Engineer", location="", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Auto-refresh full run should reuse the recent deep-scan scrape")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

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
    assert refreshed_run.progress["scrape_executed"] is False


@pytest.mark.asyncio
async def test_process_run_full_mode_does_not_skip_after_recent_quick_scan(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-quick@test.com", password_hash="mock", provider="credentials")
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
    db.add(
        Run(
            user_id=user.id,
            status="success",
            mode="quick",
            scrape_count=12,
            finished_at=now - timedelta(hours=2),
            progress={"requested_mode": "quick", "force_scrape": False, "scrape_executed": True},
        )
    )

    current_run = Run(user_id=user.id, status="pending", mode="full")
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.ranker as ranker

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="Backend Engineer", location="", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    scrape_calls = 0

    async def _scrape(*args, **kwargs):
        nonlocal scrape_calls
        scrape_calls += 1
        return []

    monkeypatch.setattr(scraper, "scrape", _scrape)

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

    monkeypatch.setattr(ranker, "score_jobs_for_user", _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(current_run.id, user.id, session_factory, mode="full")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert scrape_calls == 1
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert refreshed_run.job_count == 0
    assert refreshed_run.progress["requested_mode"] == "full"
    assert refreshed_run.progress["force_scrape"] is False
    assert refreshed_run.progress["disable_scraping"] is False
    assert refreshed_run.progress["scrape_executed"] is True


@pytest.mark.asyncio
async def test_process_run_can_rank_existing_jobs_when_scraping_disabled(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-existing@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="Backend engineer",
        scraper_hours_old=24,
        scraper_max_terms=1,
    )
    db.add(profile)

    current_run = Run(
        user_id=user.id,
        status="pending",
        mode="quick",
        progress={"requested_mode": "quick", "force_scrape": False, "disable_scraping": True},
    )
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.ranker as ranker

    async def _queries(*args, **kwargs):
        return []

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Scrape should not run when disable_scraping=true")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    score_calls = []

    async def _score_jobs_for_user(**kwargs):
        score_calls.append(kwargs)
        assert kwargs["job_urls"] is None
        return _empty_ranked_df()

    monkeypatch.setattr(ranker, "score_jobs_for_user", _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    run_id = current_run.id
    await process_run(current_run.id, user.id, session_factory, mode="quick", disable_scraping=True)

    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert len(score_calls) == 1
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert refreshed_run.progress["requested_mode"] == "quick"
    assert refreshed_run.progress["force_scrape"] is False
    assert refreshed_run.progress["disable_scraping"] is True
    assert refreshed_run.progress["scrape_executed"] is False


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

    import batch.query_plan_cache as query_plan_cache

    async def _boom(*args, **kwargs):
        raise ValueError("query builder exploded")

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _boom)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    await process_run(current_run.id, user.id, session_factory, mode="quick")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert refreshed_run.status == "failed"
    assert refreshed_run.error == "ValueError: query builder exploded"


@pytest.mark.asyncio
async def test_process_run_reraises_transient_errors_for_outer_retry(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-transient@test.com", password_hash="mock", provider="credentials")
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

    import batch.query_plan_cache as query_plan_cache

    async def _boom(*args, **kwargs):
        raise ConnectionError("temporary upstream failure")

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _boom)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    with pytest.raises(ConnectionError, match="temporary upstream failure"):
        await process_run(current_run.id, user.id, session_factory, mode="quick")

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert refreshed_run.status == "failed"
    assert refreshed_run.error == "ConnectionError: temporary upstream failure"


@pytest.mark.asyncio
async def test_claim_pending_run_sets_lease_metadata(
    db: AsyncSession,
    test_engine,
):
    user = User(email="worker-claim@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    current_run = Run(user_id=user.id, status="pending", mode="quick")
    db.add(current_run)
    await db.commit()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    request = await _claim_pending_run(session_factory, "quick")

    assert request is not None
    assert request.claim_token is not None

    run_id = current_run.id
    db.expire_all()
    refreshed_run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert refreshed_run.status == "claimed"
    assert refreshed_run.claimed_by is not None
    assert refreshed_run.claim_token == request.claim_token
    assert refreshed_run.lease_expires_at is not None
    assert refreshed_run.attempt_count == 1


@pytest.mark.asyncio
async def test_process_run_marks_cancel_requested_run_cancelled(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-cancel@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="Backend engineer",
        scraper_hours_old=24,
        scraper_max_terms=1,
    )
    db.add(profile)

    current_run = Run(user_id=user.id, status="pending", mode="quick")
    db.add(current_run)
    await db.commit()

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    request = await _claim_pending_run(session_factory, "quick")
    assert request is not None

    import batch.query_plan_cache as query_plan_cache
    import batch.ranker as ranker

    async def _queries(*args, **kwargs):
        return []

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)
    monkeypatch.setattr(ranker, "score_jobs_for_user", _score_jobs_for_user)

    run_id = current_run.id
    current_run.cancel_requested = True
    await db.commit()

    await process_run(
        request.run_id,
        request.user_id,
        session_factory,
        mode=request.mode,
        force_scrape=request.force_scrape,
        disable_scraping=request.disable_scraping,
        claim_token=request.claim_token,
    )

    db.expire_all()
    refreshed_run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert refreshed_run.status == "cancelled"
    assert refreshed_run.claim_token is None


@pytest.mark.asyncio
async def test_claim_pending_run_skips_local_runs_for_cloud_worker(db, test_engine):
    """Cloud worker (_local_worker=False) should not claim executor_type='local' runs."""
    from api.models import Run, User, Profile
    import uuid
    user = User(id=str(uuid.uuid4()), email="w@test.com", password_hash="x")
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id, onboarding_complete=True)
    db.add(profile)
    run = Run(user_id=user.id, status="pending", mode="quick", executor_type="local")
    db.add(run)
    await db.commit()

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    result = await _claim_pending_run(factory, "quick", local_worker=False)
    assert result is None


@pytest.mark.asyncio
async def test_claim_pending_run_cloud_worker_claims_null_executor_type(db, test_engine):
    """Cloud worker claims runs where executor_type is NULL or 'cloud'."""
    from api.models import Run, User, Profile
    import uuid
    user = User(id=str(uuid.uuid4()), email="w2@test.com", password_hash="x")
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id, onboarding_complete=True)
    db.add(profile)
    run = Run(user_id=user.id, status="pending", mode="quick", executor_type=None)
    db.add(run)
    await db.commit()

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    result = await _claim_pending_run(factory, "quick", local_worker=False)
    assert result is not None
