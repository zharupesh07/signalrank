import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.database import Base
from api.models import JobRaw, Profile, User
from batch.ranker import score_jobs_for_user

TEST_DB_URL = os.environ.get(
    "SIGNALRANK_BENCHMARK_DB_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/signalrank_test",
)
JOB_COUNT = int(os.environ.get("SIGNALRANK_BENCHMARK_JOB_COUNT", "120"))


def rss_mb() -> float:
    kb = int(
        subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]).decode().strip()
    )
    return round(kb / 1024, 1)


async def _seed(session_factory: async_sessionmaker) -> tuple[str, str]:
    async with session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="bench@test.com",
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


async def main() -> None:
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, resume_text = await _seed(session_factory)

    print({"stage": "before_score_jobs_for_user", "rss_mb": rss_mb(), "jobs": JOB_COUNT})

    async with session_factory() as db:
        ranked = await score_jobs_for_user(
            db=db,
            user_id=user_id,
            resume_text=resume_text,
            config_overrides=None,
        )

    print(
        {
            "stage": "after_score_jobs_for_user",
            "rss_mb": rss_mb(),
            "jobs": JOB_COUNT,
            "ranked_rows": len(ranked),
        }
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
