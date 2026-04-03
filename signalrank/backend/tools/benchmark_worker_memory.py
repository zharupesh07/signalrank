import asyncio
import os
import subprocess
import uuid
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.database import Base
from api.models import JobRaw, Profile, User
from batch.ranker import score_jobs_for_user

TEST_DB_URLS = [
    url.strip()
    for url in os.environ.get(
        "SIGNALRANK_BENCHMARK_DB_URLS",
        os.environ.get(
            "SIGNALRANK_BENCHMARK_DB_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank_test",
        ),
    ).split(",")
    if url.strip()
]
JOB_COUNT = int(os.environ.get("SIGNALRANK_BENCHMARK_JOB_COUNT", "120"))
ENABLE_AGENTIC = os.environ.get("SIGNALRANK_BENCHMARK_ENABLE_AGENTIC", "0").lower() in {"1", "true", "yes"}
THREAD_SETTINGS = [
    int(item.strip())
    for item in os.environ.get("SIGNALRANK_BENCHMARK_EMBED_THREADS_LIST", "1,4").split(",")
    if item.strip()
]
EMBED_BATCH_SIZES = [
    int(item.strip())
    for item in os.environ.get("SIGNALRANK_BENCHMARK_EMBED_BATCH_SIZES", "4,8,16,32").split(",")
    if item.strip()
]
MODEL_SPECS = [
    item.strip()
    for item in os.environ.get(
        "SIGNALRANK_BENCHMARK_MODEL_LIST",
        "sentence-transformers/all-MiniLM-L6-v2,BAAI/bge-small-en-v1.5,sentence-transformers/paraphrase-MiniLM-L3-v2",
    ).split(",")
    if item.strip()
]


def rss_mb() -> float:
    kb = int(
        subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]).decode().strip()
    )
    return round(kb / 1024, 1)


async def _seed(session_factory: async_sessionmaker) -> tuple[str, str]:
    async with session_factory() as db:
        seed_id = uuid.uuid4().hex[:10]
        user = User(
            id=str(uuid.uuid4()),
            email=f"bench-{seed_id}@test.com",
            password_hash="x",
            provider="credentials",
        )
        db.add(user)
        await db.flush()

        profile = Profile(
            user_id=user.id,
            resume_text="Platform engineer with Python, Kubernetes, AWS, MLOps, LLM, RAG, Docker, Terraform.",
            target_roles=["AI Platform Engineer", "MLOps Engineer"],
            preferred_locations=["Bangalore", "Remote"],
            role_intent="ai_platform",
            onboarding_complete=True,
            scraper_max_terms=1,
            scraper_hours_old=24,
            config_overrides={
                "ranking": {"agentic_matching": {"enabled": ENABLE_AGENTIC}},
            },
        )
        db.add(profile)

        jobs = [
            JobRaw(
                job_url=f"https://example.com/bench-job-{i}",
                title="ML Platform Engineer" if i % 4 == 0 else "Platform Engineer",
                company=f"Company {i % 25}",
                description=(
                    "Build model serving, platform tooling, kubernetes infrastructure, "
                    "python services, llm pipelines, and cloud automation. "
                )
                * 8,
                location="Bangalore",
                site="indeed",
                date_posted=datetime.now(timezone.utc),
                ingested_at=datetime.now(timezone.utc),
                role_clusters=["ai_ml_data"],
            )
            for i in range(JOB_COUNT)
        ]
        db.add_all(jobs)
        await db.commit()
        return user.id, profile.resume_text or ""


async def _run_for_db_url(db_url: str, embed_threads: int, embed_batch_size: int, model_name: str) -> None:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, resume_text = await _seed(session_factory)

    print({
        "stage": "before_score_jobs_for_user",
        "db_url": db_url,
        "embed_threads": embed_threads,
        "embed_batch_size": embed_batch_size,
        "model_name": model_name,
        "rss_mb": rss_mb(),
        "jobs": JOB_COUNT,
    })
    t0 = time.monotonic()
    async with session_factory() as db:
        ranked = await score_jobs_for_user(
            db=db,
            user_id=user_id,
            resume_text=resume_text,
            config_overrides={
                "embeddings": {
                    "model_name": model_name,
                    "session_intra_op_threads": embed_threads,
                    "session_inter_op_threads": 1,
                },
                "batch": {
                    "embed_batch_size": embed_batch_size,
                },
                "ranking": {"agentic_matching": {"enabled": ENABLE_AGENTIC}},
            },
        )
    duration_s = round(time.monotonic() - t0, 2)
    print(
        {
            "stage": "after_score_jobs_for_user",
            "db_url": db_url,
            "embed_threads": embed_threads,
            "embed_batch_size": embed_batch_size,
            "model_name": model_name,
            "rss_mb": rss_mb(),
            "jobs": JOB_COUNT,
            "ranked_rows": len(ranked),
            "duration_s": duration_s,
        }
    )
    await engine.dispose()


async def main() -> None:
    for db_url in TEST_DB_URLS:
        for model_name in MODEL_SPECS:
            for threads in THREAD_SETTINGS:
                for batch_size in EMBED_BATCH_SIZES:
                    await _run_for_db_url(db_url, threads, batch_size, model_name)


if __name__ == "__main__":
    asyncio.run(main())
