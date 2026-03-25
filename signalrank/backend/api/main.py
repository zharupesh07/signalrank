import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from api.config import settings
from api.database import AsyncSessionLocal
from api.deps_llm import get_llm_client
from api.models import Run
from api.routes import applications, auth, ingest, jobs, onboarding, profile, recruiters, resume, runs
from batch.archival_worker import archival_worker_loop, recover_stuck_archival_tasks
from batch.resume_worker import boot_scan, recover_stuck_generation_tasks, resume_worker_loop
from batch.worker import get_queue, worker_loop

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_resume_worker_task: asyncio.Task | None = None
_archival_worker_task: asyncio.Task | None = None


async def _resume_worker_watchdog(session_factory, llm) -> None:
    """Run resume_worker_loop and restart it if it crashes unexpectedly."""
    while True:
        try:
            await resume_worker_loop(session_factory, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resume worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _archival_worker_watchdog(session_factory, llm) -> None:
    """Run archival_worker_loop and restart it if it crashes unexpectedly."""
    while True:
        try:
            await archival_worker_loop(session_factory, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Archival worker crashed — restarting in 10s")
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task, _resume_worker_task, _archival_worker_task
    _worker_task = asyncio.create_task(worker_loop(AsyncSessionLocal))

    llm = get_llm_client()

    # Crash recovery: reset any tasks left in "running" state from a prior restart
    try:
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_generation_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck generation task(s) from prior crash", recovered)
    except Exception:
        logger.warning("Generation task recovery failed", exc_info=True)

    try:
        async with AsyncSessionLocal() as db:
            await boot_scan(db)
    except Exception:
        logger.warning("Boot scan failed", exc_info=True)

    _resume_worker_task = asyncio.create_task(
        _resume_worker_watchdog(AsyncSessionLocal, llm)
    )

    try:
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_archival_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck archival task(s) from prior crash", recovered)
    except Exception:
        logger.warning("Archival task recovery failed", exc_info=True)

    _archival_worker_task = asyncio.create_task(
        _archival_worker_watchdog(AsyncSessionLocal, llm)
    )

    # Re-queue any runs that were left stuck (pending/scraping) from a prior restart
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Run).where(Run.status.in_(["pending", "scraping"]))
        )
        stuck = result.scalars().all()
        if stuck:
            logger.info("Recovering %d stuck run(s) from prior restart", len(stuck))
            queue = get_queue()
            for run in stuck:
                await db.execute(
                    update(Run).where(Run.id == run.id).values(status="pending")
                )
                await queue.put((str(run.id), str(run.user_id)))
            await db.commit()

    yield
    for t in (_worker_task, _resume_worker_task, _archival_worker_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass


app = FastAPI(title="SignalRank API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(runs.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(onboarding.router)
app.include_router(resume.router)
app.include_router(recruiters.router)
app.include_router(ingest.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
