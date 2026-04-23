from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import JobRaw, JobResult, Profile, Run, User
from batch.query_builder import SearchQuery
from batch.worker import _claim_pending_run, _embed_new_jobs, process_run


def _empty_ranked_df():
    return pd.DataFrame(columns=["id", "final_score", "semantic_score", "skills_score",
                                  "company_score", "seniority_score_dim", "location_score",
                                  "recency_score", "company_tier", "is_contract"])


def _ranked_df_for(job: JobRaw):
    return pd.DataFrame(
        [
            {
                "id": job.id,
                "final_score": 91.0,
                "semantic_score": 0.88,
                "skills_score": 90.0,
                "company_score": 80.0,
                "seniority_score_dim": 85.0,
                "location_score": 95.0,
                "recency_score": 100.0,
                "company_tier": "tier_a",
                "is_contract": False,
            }
        ]
    )


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
    import batch.worker as worker_module

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

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

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
    import batch.worker as worker_module

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="Backend Engineer", location="", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Auto-refresh full run should reuse the recent deep-scan scrape")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

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
    import batch.worker as worker_module

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

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

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
    import batch.worker as worker_module

    async def _queries(*args, **kwargs):
        return []

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Scrape should not run when disable_scraping=true")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    score_calls = []

    async def _score_jobs_for_user(**kwargs):
        score_calls.append(kwargs)
        assert kwargs["job_urls"] == []
        return _empty_ranked_df()

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

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
async def test_process_run_rerank_only_reuses_latest_scrape_backed_run_corpus(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-rerank-corpus@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="MLOps engineer",
        scraper_hours_old=168,
        scraper_max_terms=3,
    )
    db.add(profile)

    previous_run = Run(
        user_id=user.id,
        status="success",
        mode="full",
        scrape_count=25,
        job_count=2,
        progress={"requested_mode": "full", "force_scrape": True, "scrape_executed": True},
    )
    db.add(previous_run)
    await db.flush()
    previous_run_id = previous_run.id

    job_a = JobRaw(
        job_url="https://jobs.example.com/a",
        title="MLOps Engineer",
        company="Acme",
        description="Build model deployment pipelines",
        location="Bangalore",
        site="indeed",
    )
    job_b = JobRaw(
        job_url="https://jobs.example.com/b",
        title="AI Platform Engineer",
        company="Beta",
        description="Own the AI platform stack",
        location="Pune",
        site="indeed",
    )
    db.add_all([job_a, job_b])
    await db.flush()

    db.add_all(
        [
            JobResult(run_id=previous_run.id, user_id=user.id, job_id=job_a.id, final_score=91.0),
            JobResult(run_id=previous_run.id, user_id=user.id, job_id=job_b.id, final_score=88.0),
        ]
    )

    current_run = Run(
        user_id=user.id,
        status="pending",
        mode="full",
        progress={"requested_mode": "full", "force_scrape": False, "disable_scraping": True},
    )
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.worker as worker_module

    async def _queries(*args, **kwargs):
        return []

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Scrape should not run when disable_scraping=true")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    score_calls = []

    async def _score_jobs_for_user(**kwargs):
        score_calls.append(kwargs)
        assert kwargs["job_urls"] == [
            "https://jobs.example.com/a",
            "https://jobs.example.com/b",
        ]
        return _empty_ranked_df()

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    run_id = current_run.id
    await process_run(current_run.id, user.id, session_factory, mode="full", disable_scraping=True)

    db.expire_all()
    refreshed_run = (
        await db.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert len(score_calls) == 1
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert refreshed_run.progress["disable_scraping"] is True
    assert refreshed_run.progress["scrape_executed"] is False
    assert refreshed_run.progress["corpus_source"] == "latest_scrape_run"
    assert refreshed_run.progress["corpus_run_id"] == previous_run_id
    assert refreshed_run.progress["corpus_job_count"] == 2
    assert refreshed_run.progress["rerank_corpus_jobs"] == 2


@pytest.mark.asyncio
async def test_process_run_archives_expired_jobs_after_ranking(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-availability@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()
    user_id = user.id

    profile = Profile(user_id=user_id, resume_text="Backend engineer")
    job = JobRaw(
        job_url="https://example.com/jobs/open-or-expired",
        title="Backend Engineer",
        company="Example",
        description="Build backend services",
        location="Remote",
        site="indeed",
    )
    current_run = Run(
        user_id=user_id,
        status="pending",
        mode="quick",
        progress={
            "requested_mode": "quick",
            "force_scrape": False,
            "disable_scraping": True,
        },
    )
    db.add_all([profile, job, current_run])
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.worker as worker_module

    async def _queries(*args, **kwargs):
        return []

    async def _score_jobs_for_user(**kwargs):
        return _ranked_df_for(job)

    archive_calls = []

    async def _archive_expired_jobs_for_user(db, *, user_id, run_id=None, limit=50, **kwargs):
        archive_calls.append({"user_id": user_id, "run_id": run_id, "limit": limit})
        return {
            "checked": 1,
            "expired": 1,
            "unknown": 0,
            "archived": 1,
            "tracker_archived": 0,
            "jobs": [],
        }

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)
    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)
    monkeypatch.setattr(
        worker_module,
        "archive_expired_jobs_for_user",
        _archive_expired_jobs_for_user,
    )
    monkeypatch.setattr(worker_module.settings, "job_availability_archive_after_run", True)
    monkeypatch.setattr(worker_module.settings, "job_availability_archive_limit", 100)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    run_id = current_run.id
    await process_run(run_id, user_id, session_factory, mode="quick", disable_scraping=True)

    db.expire_all()
    refreshed_run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert refreshed_run.status == "success"
    assert archive_calls == [{"user_id": user_id, "run_id": run_id, "limit": 100}]
    assert refreshed_run.progress["availability_checked"] == 1
    assert refreshed_run.progress["availability_archived"] == 1
    assert refreshed_run.progress["tracker_archived"] == 0


@pytest.mark.asyncio
async def test_process_run_prunes_low_signal_fresh_jobs_before_embed_and_rank(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-prune@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="MLOps engineer working on Kubernetes, Terraform, and AI platform systems",
        scraper_hours_old=168,
        scraper_max_terms=3,
        target_roles=["MLOps Engineer", "AI Platform Engineer"],
        preferred_locations=["Bangalore"],
        skills=["Kubernetes", "Terraform", "Python"],
    )
    db.add(profile)

    current_run = Run(user_id=user.id, status="pending", mode="full")
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.worker as worker_module
    import batch.worker as worker

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="MLOps Engineer", location="Bangalore", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _scrape(*args, **kwargs):
        db_session = kwargs["db"]
        db_session.add_all(
            [
                JobRaw(
                    job_url="https://jobs.example.com/relevant",
                    title="Senior MLOps Engineer",
                    company="Acme",
                    description="Build AI platform systems with Kubernetes, Terraform, and Python in Bangalore.",
                    location="Bangalore",
                    role_clusters=["ai_ml", "infra"],
                    job_profile={
                        "role_titles_normalized": ["Senior MLOps Engineer"],
                        "required_skills": ["Kubernetes", "Terraform", "Python"],
                        "preferred_skills": ["AWS"],
                        "location_normalized": "Bangalore",
                        "domain": "AI / ML",
                        "role_family": "Platform / Infrastructure",
                        "description_quality": 0.96,
                        "red_flags": [],
                    },
                ),
                JobRaw(
                    job_url="https://jobs.example.com/noise",
                    title="Sales Development Representative",
                    company="NoiseCo",
                    description="Fast paced environment. Dynamic environment. Stakeholders everywhere.",
                    location="Mumbai",
                    role_clusters=["general"],
                    job_profile={
                        "role_titles_normalized": ["Sales Development Representative"],
                        "required_skills": ["Salesforce"],
                        "preferred_skills": [],
                        "location_normalized": "Mumbai",
                        "domain": "General",
                        "role_family": "General",
                        "description_quality": 0.2,
                        "red_flags": ["very_short_description", "boilerplate_heavy"],
                    },
                ),
            ]
        )
        await db_session.commit()
        return ["https://jobs.example.com/relevant", "https://jobs.example.com/noise"]

    monkeypatch.setattr(scraper, "scrape", _scrape)

    embed_calls = []

    async def _embed(db_session, job_urls, update_progress=None):
        embed_calls.append(list(job_urls))

    monkeypatch.setattr(worker, "_embed_new_jobs", _embed)

    score_calls = []

    async def _score_jobs_for_user(**kwargs):
        score_calls.append(kwargs)
        assert kwargs["job_urls"] == ["https://jobs.example.com/relevant"]
        return _empty_ranked_df()

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    run_id = current_run.id
    await process_run(current_run.id, user.id, session_factory, mode="full")

    db.expire_all()
    refreshed_run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 2
    assert embed_calls == [["https://jobs.example.com/relevant"]]
    assert len(score_calls) == 1


@pytest.mark.asyncio
async def test_process_run_reuses_incremental_cached_urls_without_network_scrape(
    db: AsyncSession,
    test_engine,
    monkeypatch,
):
    user = User(email="worker-incremental@test.com", password_hash="mock", provider="credentials")
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        resume_text="MLOps engineer",
        scraper_hours_old=24,
        scraper_max_terms=1,
        target_roles=["MLOps Engineer"],
    )
    db.add(profile)

    current_run = Run(user_id=user.id, status="pending", mode="full")
    db.add(current_run)
    await db.commit()

    import batch.query_plan_cache as query_plan_cache
    import batch.scraper as scraper
    import batch.worker as worker_module
    import batch.worker as worker

    async def _queries(*args, **kwargs):
        return [SearchQuery(term="MLOps Engineer", location="Bangalore", country="India")]

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)

    async def _plan_incremental_scrape(queries, config, db_session):
        return [], ["https://jobs.example.com/cached-relevant"]

    monkeypatch.setattr(scraper, "plan_incremental_scrape", _plan_incremental_scrape)

    async def _scrape(*args, **kwargs):
        raise AssertionError("Network scrape should not run when all queries are fresh")

    monkeypatch.setattr(scraper, "scrape", _scrape)

    db.add(
        JobRaw(
            job_url="https://jobs.example.com/cached-relevant",
            title="MLOps Engineer",
            company="Acme",
            description="Kubernetes Terraform platform engineering role",
            location="Bangalore",
            site="indeed",
            role_clusters=["ai_ml", "infra"],
            job_profile={
                "role_titles_normalized": ["MLOps Engineer"],
                "required_skills": ["Kubernetes", "Terraform"],
                "preferred_skills": ["Python"],
                "location_normalized": "Bangalore",
                "domain": "AI / ML",
                "role_family": "Platform / Infrastructure",
                "description_quality": 0.95,
                "red_flags": [],
            },
            embedding=[0.1] * 384,
        )
    )
    await db.commit()

    embed_calls = []

    async def _embed(db_session, job_urls, update_progress=None):
        embed_calls.append(list(job_urls))

    monkeypatch.setattr(worker, "_embed_new_jobs", _embed)

    score_calls = []

    async def _score_jobs_for_user(**kwargs):
        score_calls.append(kwargs)
        assert kwargs["job_urls"] == ["https://jobs.example.com/cached-relevant"]
        return _empty_ranked_df()

    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    run_id = current_run.id
    await process_run(current_run.id, user.id, session_factory, mode="full")

    db.expire_all()
    refreshed_run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert refreshed_run.status == "success"
    assert refreshed_run.scrape_count == 0
    assert embed_calls == [["https://jobs.example.com/cached-relevant"]]
    assert len(score_calls) == 1


@pytest.mark.asyncio
async def test_embed_new_jobs_skips_rows_with_existing_embedding(db: AsyncSession, monkeypatch):
    db.add_all(
        [
            JobRaw(
                job_url="https://jobs.example.com/embedded",
                title="Embedded Role",
                company="Acme",
                description="Existing embedding row",
                location="Bangalore",
                site="test",
                embedding=[0.1] * 384,
            ),
            JobRaw(
                job_url="https://jobs.example.com/missing",
                title="Missing Role",
                company="Acme",
                description="Needs embedding generation",
                location="Bangalore",
                site="test",
            ),
        ]
    )
    await db.commit()

    import batch.worker as worker

    store_calls = []

    async def _store_job_embeddings(_db, rows):
        store_calls.append(rows)

    class _FakeCache:
        def __init__(self, *args, **kwargs):
            pass

        async def fetch(self, keys):
            return {}

        async def store_vectors(self, rows):
            return None

    class _FakeEngine:
        def __init__(self, cfg):
            self.cfg = cfg

        def embed(self, texts):
            class _Vec:
                def __init__(self):
                    self._value = [0.2] * 384

                def tolist(self):
                    return self._value

            return [_Vec() for _ in texts]

    monkeypatch.setattr(worker, "PgEmbeddingCache", _FakeCache)
    monkeypatch.setattr(worker, "store_job_embeddings", _store_job_embeddings)

    import domain.embeddings as embeddings_mod

    monkeypatch.setattr(embeddings_mod, "EmbeddingEngine", _FakeEngine)

    await _embed_new_jobs(db, ["https://jobs.example.com/embedded", "https://jobs.example.com/missing"])

    flattened_urls = [job_url for batch in store_calls for job_url, _ in batch]
    assert flattened_urls == ["https://jobs.example.com/missing"]


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
    import batch.worker as worker_module

    async def _queries(*args, **kwargs):
        return []

    async def _score_jobs_for_user(**kwargs):
        return _empty_ranked_df()

    monkeypatch.setattr(query_plan_cache, "get_cached_queries", _queries)
    monkeypatch.setattr(worker_module, "_get_score_jobs_for_user", lambda: _score_jobs_for_user)

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
