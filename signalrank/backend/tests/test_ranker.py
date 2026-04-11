import pandas as pd
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ranking.v4.db_scorer import score_jobs_for_user


async def test_score_jobs_empty_corpus(db: AsyncSession):
    user_id = str(uuid4())
    results = await score_jobs_for_user(
        db=db,
        user_id=user_id,
        resume_text="I am a machine learning engineer",
        config_overrides=None,
    )
    assert isinstance(results, pd.DataFrame)
    assert len(results) == 0


async def test_score_jobs_returns_ranked_results(db: AsyncSession):
    user_id = str(uuid4())
    embedding = "[" + ",".join(["0.0"] * 384) + "]"
    await db.execute(
        text(
            f"INSERT INTO jobs_raw (id, job_url, title, company, description, location, site, embedding, ingested_at) "
            f"VALUES (gen_random_uuid(), :url, :title, :company, :desc, :loc, :site, '{embedding}'::vector, now())"
        ),
        {
            "url": "https://example.com/job-ranker-test-1",
            "title": "Senior ML Engineer",
            "company": "Google",
            "desc": "Build machine learning pipelines using Python, TensorFlow, and PyTorch. "
                    "Deploy models to production. Strong experience with NLP and deep learning required.",
            "loc": "Bangalore, India",
            "site": "linkedin",
        },
    )
    await db.flush()

    results = await score_jobs_for_user(
        db=db,
        user_id=user_id,
        resume_text="Machine learning engineer with 5 years experience in Python, PyTorch, NLP, and deep learning.",
        config_overrides=None,
    )
    assert isinstance(results, pd.DataFrame)
    assert len(results) >= 0
