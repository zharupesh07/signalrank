import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from api.config import settings
from api.database import AsyncSessionLocal
from api.models import Run
from api.routes import applications, auth, jobs, onboarding, profile, recruiters, resume, runs
from batch.worker import get_queue, worker_loop

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task
    _worker_task = asyncio.create_task(worker_loop(AsyncSessionLocal))

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
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
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


@app.get("/health")
async def health():
    return {"status": "ok"}
