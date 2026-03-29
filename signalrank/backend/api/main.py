import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text

from api.config import settings
from api.database import AsyncSessionLocal, engine
from api.deps_llm import get_llm_client
from api.routes import admin, applications, auth, ingest, jobs, onboarding, profile, recruiters, resume, runs
from batch.archival_worker import archival_worker_loop, recover_stuck_archival_tasks
from batch.resume_worker import boot_scan, recover_stuck_generation_tasks, resume_worker_loop
from batch.worker import boot_embed_uncached_jobs, worker_loop

# --- Structured JSON logging ---
_handler = logging.StreamHandler()
_handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_handler]

logger = logging.getLogger(__name__)
logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

# --- Rate limiter (in-memory, no Redis — suitable for single-instance 512MB) ---
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

_worker_task: asyncio.Task | None = None
_resume_worker_task: asyncio.Task | None = None
_archival_worker_task: asyncio.Task | None = None
_boot_tasks: list[asyncio.Task] = []


async def _resume_worker_watchdog(session_factory, llm) -> None:
    while True:
        try:
            await resume_worker_loop(session_factory, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resume worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _archival_worker_watchdog(session_factory, llm) -> None:
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
    global _worker_task, _resume_worker_task, _archival_worker_task, _boot_tasks
    _boot_tasks = []

    if settings.run_api_worker:
        _worker_task = asyncio.create_task(worker_loop(AsyncSessionLocal))

    llm = None
    if settings.run_resume_worker or settings.run_archival_worker:
        llm = get_llm_client()

    if settings.run_resume_worker:
        try:
            async with AsyncSessionLocal() as db:
                recovered = await recover_stuck_generation_tasks(db)
                if recovered:
                    logger.info("Recovered %d stuck generation task(s) from prior crash", recovered)
        except Exception:
            logger.warning("Generation task recovery failed", exc_info=True)

        _resume_worker_task = asyncio.create_task(
            _resume_worker_watchdog(AsyncSessionLocal, llm)
        )

    if settings.run_boot_scan:
        async def _delayed_boot_scan():
            await asyncio.sleep(30)
            try:
                async with AsyncSessionLocal() as db:
                    await boot_scan(db)
            except Exception:
                logger.warning("Boot scan failed", exc_info=True)

        _boot_tasks.append(asyncio.create_task(_delayed_boot_scan()))

    if settings.run_boot_embed:
        async def _delayed_boot_embed():
            await asyncio.sleep(60)
            try:
                await boot_embed_uncached_jobs(AsyncSessionLocal)
            except Exception:
                logger.warning("Boot embed failed", exc_info=True)

        _boot_tasks.append(asyncio.create_task(_delayed_boot_embed()))

    if settings.run_archival_worker:
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

    yield
    for t in (_worker_task, _resume_worker_task, _archival_worker_task, *_boot_tasks):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass


app = FastAPI(title="SignalRank API", version="0.1.0", lifespan=lifespan)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(profile.router)
app.include_router(runs.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(onboarding.router)
app.include_router(resume.router)
app.include_router(recruiters.router)
app.include_router(ingest.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception:
        logger.exception("Health check DB ping failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "db": "unreachable"},
        )
