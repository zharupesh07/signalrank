import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.config import settings
from api.helpers import get_resume_template
from api.models import Application, GenerationQueue, JobRaw, Profile, TailoredResume
from api.sql_compat import conflict_kwargs, dialect_insert, dialect_name
from batch.context import load_base_config
from llm.email_generator import generate_email
from llm.openrouter import OpenRouterClient
from llm.resume_tailor import compile_pdf, render_typst, tailor_resume

logger = logging.getLogger(__name__)

CONCURRENCY = max(1, settings.resume_worker_concurrency)
_cfg = load_base_config()
MAX_TASK_RETRIES = _cfg.get("retry", {}).get("resume_task_max", 3)
POLL_INTERVAL = _cfg.get("batch", {}).get("worker_poll_interval", 5)



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
    if existing and existing.email_body and existing.pdf_bytes:
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
    selected_template = get_resume_template(profile)

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
        if existing and existing.email_body and existing.pdf_bytes and (existing.template or "classic") == selected_template:
            tailored = existing
        elif existing and existing.content_json:
            # content already generated but PDF missing or stale template — recompile from cached JSON
            from llm.resume_tailor import TailoredContent
            content_obj = TailoredContent(**existing.content_json)
            typst_src = render_typst(content_obj, selected_template)
            existing.pdf_bytes = compile_pdf(typst_src)
            existing.template = selected_template
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
            typst_src = render_typst(content, selected_template)
            pdf = compile_pdf(typst_src)
            if existing:
                existing.content_json = content_dict
                existing.template = selected_template
                existing.pdf_bytes = pdf
                tailored = existing
            else:
                tailored = TailoredResume(
                    user_id=task.user_id,
                    job_id=task.job_id,
                    content_json=content_dict,
                    template=selected_template,
                    pdf_bytes=pdf,
                )
                db.add(tailored)
                await db.flush()
            logger.info("Generated resume for user=%s job=%s", task.user_id, task.job_id)

        if not tailored.email_body:
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
        await db.rollback()
        new_retry_count = (task.retry_count or 0) + 1
        if new_retry_count >= MAX_TASK_RETRIES:
            new_status = "failed"
            next_retry_at = None
        else:
            new_status = "pending"
            backoff = min(2 ** (new_retry_count + 1), 120) + random.uniform(0, 10)
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        await db.execute(
            update(GenerationQueue)
            .where(GenerationQueue.id == task.id)
            .values(
                status=new_status,
                error=str(e),
                retry_count=new_retry_count,
                next_retry_at=next_retry_at,
            )
        )
        await db.commit()


async def recover_stuck_generation_tasks(db: AsyncSession) -> int:
    """Reset tasks left in 'running' state from a prior crash back to 'pending'."""
    result = await db.execute(
        update(GenerationQueue)
        .where(GenerationQueue.status == "running")
        .values(status="pending", next_retry_at=None)
        .returning(GenerationQueue.id)
    )
    count = len(result.fetchall())
    if count:
        await db.commit()
    return count


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
            (TailoredResume.id.is_(None)) | (TailoredResume.email_body.is_(None)) | (TailoredResume.email_body == "") | (TailoredResume.pdf_bytes.is_(None)),
        )
    )
    rows = result.all()
    if not rows:
        logger.info("Boot scan: all tracked jobs already have resumes and emails")
        return

    await db.execute(
        dialect_insert(db, GenerationQueue)
        .values([{"user_id": r.user_id, "job_id": r.job_id} for r in rows])
        .on_conflict_do_nothing(**conflict_kwargs(db, constraint="uq_generation_queue_user_job"))
    )
    await db.commit()
    logger.info("Boot scan: enqueued %d resume generation tasks", len(rows))


async def force_regenerate_all(db: AsyncSession, user_id: str) -> int:
    """Delete all cached resumes+emails for a user and re-enqueue generation for all tracked jobs."""
    tracked = await db.execute(
        select(Application.job_id).where(
            Application.user_id == user_id,
            Application.job_id.isnot(None),
        )
    )
    job_ids = [r.job_id for r in tracked.all()]
    if not job_ids:
        return 0

    await db.execute(
        update(TailoredResume)
        .where(TailoredResume.user_id == user_id, TailoredResume.job_id.in_(job_ids))
        .values(content_json=None, pdf_bytes=None, email_subject=None, email_body=None)
    )
    await db.execute(
        update(GenerationQueue)
        .where(GenerationQueue.user_id == user_id, GenerationQueue.job_id.in_(job_ids))
        .values(status="pending", error=None)
    )
    # Enqueue any that don't have a queue row yet
    await db.execute(
        dialect_insert(db, GenerationQueue)
        .values([{"user_id": user_id, "job_id": jid} for jid in job_ids])
        .on_conflict_do_update(
            **conflict_kwargs(db, constraint="uq_generation_queue_user_job"),
            set_={"status": "pending", "error": None},
        )
    )
    await db.commit()
    logger.info("Force regenerate: reset %d jobs for user=%s", len(job_ids), user_id)
    return len(job_ids)


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
                now = datetime.now(timezone.utc)
                stmt = (
                    select(GenerationQueue)
                    .where(
                        GenerationQueue.status == "pending",
                        (GenerationQueue.next_retry_at.is_(None)) | (GenerationQueue.next_retry_at <= now),
                    )
                    .order_by(GenerationQueue.created_at)
                    .limit(CONCURRENCY)
                )
                if dialect_name(db) != "sqlite":
                    stmt = stmt.with_for_update(skip_locked=True)
                result = await db.execute(stmt)
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
