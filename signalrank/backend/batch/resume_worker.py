import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert

from api.models import Application, GenerationQueue, JobRaw, Profile, TailoredResume
from llm.email_generator import generate_email
from llm.openrouter import OpenRouterClient
from llm.resume_tailor import tailor_resume

logger = logging.getLogger(__name__)

CONCURRENCY = 3


async def process_generation_task(
    task: GenerationQueue,
    db: AsyncSession,
    llm: OpenRouterClient,
) -> None:
    """Process one generation task. Idempotent — skips if TailoredResume already exists."""
    existing_res = await db.execute(
        select(TailoredResume).where(
            TailoredResume.user_id == task.user_id,
            TailoredResume.job_id == task.job_id,
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing and existing.email_body:
        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(status="done")
        )
        await db.commit()
        return

    profile_res = await db.execute(
        select(Profile).where(Profile.user_id == task.user_id)
    )
    profile = profile_res.scalar_one_or_none()
    if not profile or not profile.resume_text:
        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(status="failed", error="No resume text found for user")
        )
        await db.commit()
        return

    job_res = await db.execute(select(JobRaw).where(JobRaw.id == task.job_id))
    job = job_res.scalar_one_or_none()
    if not job:
        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(status="failed", error="Job not found")
        )
        await db.commit()
        return

    try:
        if existing:
            tailored = existing
        else:
            content = await tailor_resume(
                resume_text=profile.resume_text,
                job_title=job.title or "",
                job_description=job.description or "",
                llm=llm,
            )
            content_dict = {
                "name": content.name, "position": content.position,
                "email": content.email, "phone": content.phone,
                "homepage": content.homepage, "linkedin": content.linkedin,
                "github": content.github, "location": content.location,
                "summary": content.summary, "skills": content.skills,
                "experiences": content.experiences, "education": content.education,
                "projects": content.projects, "certifications": content.certifications,
            }
            tailored = TailoredResume(
                user_id=task.user_id,
                job_id=task.job_id,
                content_json=content_dict,
                template="classic",
            )
            db.add(tailored)
            await db.flush()
            logger.info("Generated resume for user=%s job=%s", task.user_id, task.job_id)

        bullets: list[str] = []
        if tailored.content_json:
            for exp in tailored.content_json.get("experiences", [])[:2]:
                bullets.extend(exp.get("bullets", [])[:3])

        email = await generate_email(
            jd=job.description or "",
            company=job.company or "",
            role=job.title or "",
            recruiter_name="Hiring Manager",
            tailored_bullets=bullets,
            job_url=job.job_url if hasattr(job, "job_url") else None,
            llm=llm,
        )
        tailored.email_subject = email.subject
        tailored.email_body = email.body

        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(status="done")
        )
        await db.commit()
        logger.info("Generated email for user=%s job=%s", task.user_id, task.job_id)
    except Exception as e:
        logger.warning("Generation failed for job=%s: %s", task.job_id, e)
        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(status="failed", error=str(e))
        )
        await db.commit()


async def boot_scan(db: AsyncSession) -> None:
    """Enqueue generation for all tracked jobs that lack a TailoredResume. Idempotent."""
    result = await db.execute(
        select(Application.user_id, Application.job_id)
        .outerjoin(
            TailoredResume,
            (TailoredResume.user_id == Application.user_id) &
            (TailoredResume.job_id == Application.job_id),
        )
        .where(
            Application.job_id.isnot(None),
            (TailoredResume.id.is_(None)) | (TailoredResume.email_body.is_(None)),
        )
    )
    rows = result.all()
    if not rows:
        logger.info("Boot scan: all tracked jobs already have resumes and emails")
        return

    await db.execute(
        insert(GenerationQueue)
        .values([{"user_id": r.user_id, "job_id": r.job_id} for r in rows])
        .on_conflict_do_nothing(constraint="uq_generation_queue_user_job")
    )
    await db.commit()
    logger.info("Boot scan: enqueued %d resume generation tasks", len(rows))


async def resume_worker_loop(
    session_factory: async_sessionmaker,
    llm: OpenRouterClient,
) -> None:
    """Poll generation_queue for pending tasks, process up to CONCURRENCY at a time."""
    logger.info("Resume worker started")

    async def _run_task(t):
        async with session_factory() as task_db:
            await process_generation_task(t, task_db, llm)

    while True:
        tasks: list = []
        try:
            async with session_factory() as db:
                result = await db.execute(
                    select(GenerationQueue)
                    .where(GenerationQueue.status == "pending")
                    .order_by(GenerationQueue.created_at)
                    .limit(CONCURRENCY)
                    .with_for_update(skip_locked=True)
                )
                tasks = result.scalars().all()

                if tasks:
                    for task in tasks:
                        await db.execute(
                            update(GenerationQueue)
                            .where(GenerationQueue.id == task.id)
                            .values(status="running")
                        )
                    await db.commit()

            if tasks:
                await asyncio.gather(
                    *[_run_task(t) for t in tasks],
                    return_exceptions=True,
                )
        except Exception:
            logger.exception("Resume worker loop error")

        await asyncio.sleep(5)
