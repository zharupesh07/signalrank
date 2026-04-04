import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from api.config import (
    api_runtime_flags,
    effective_allow_origin_regex,
    effective_allowed_origins,
    settings,
)
from api.database import AsyncSessionLocal, _parse_url, ensure_runtime_schema_compatibility
from api.deps_llm import get_llm_client
from api.logging_setup import configure_logging
from api.routes import admin, applications, auth, dev, ingest, jobs, onboarding, profile, recruiters, resume, runs

configure_logging()
logger = logging.getLogger(__name__)

# --- Rate limiter (in-memory, no Redis — suitable for single-instance 512MB) ---
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

_worker_task: asyncio.Task | None = None
_resume_worker_task: asyncio.Task | None = None
_archival_worker_task: asyncio.Task | None = None
_maintenance_worker_task: asyncio.Task | None = None
_boot_tasks: list[asyncio.Task] = []
_schema_heal_lock = asyncio.Lock()


def _looks_like_undefined_column_error(exc: Exception) -> bool:
    text = str(exc)
    return "UndefinedColumnError" in text or "undefined column" in text.lower() or "does not exist" in text.lower()


async def _heal_schema_once() -> None:
    async with _schema_heal_lock:
        await ensure_runtime_schema_compatibility()


def _log_api_runtime_role(runtime_flags: dict[str, bool]) -> None:
    logger.info(
        "API role: http=true queue_worker=%s resume_worker=%s archival_worker=%s boot_scan=%s boot_embed=%s",
        runtime_flags["run_api_worker"],
        runtime_flags["run_resume_worker"],
        runtime_flags["run_archival_worker"],
        runtime_flags["run_boot_scan"],
        runtime_flags["run_boot_embed"],
    )
    if not runtime_flags["run_api_worker"]:
        logger.info(
            "API split mode: this process will create pending runs in DB only; a separate worker service must claim them"
        )


def _log_cors_settings() -> None:
    logger.info(
        "CORS config: allow_origins=%s allow_origin_regex=%s",
        effective_allowed_origins(),
        effective_allow_origin_regex(),
    )


async def _resume_worker_watchdog(session_factory, llm) -> None:
    from batch.resume_worker import resume_worker_loop

    while True:
        try:
            await resume_worker_loop(session_factory, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resume worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _archival_worker_watchdog(session_factory, llm) -> None:
    from batch.archival_worker import archival_worker_loop

    while True:
        try:
            await archival_worker_loop(session_factory, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Archival worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _maintenance_worker_watchdog(session_factory) -> None:
    from batch.maintenance import maintenance_loop

    while True:
        try:
            await maintenance_loop(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Maintenance worker crashed — restarting in 10s")
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task, _resume_worker_task, _archival_worker_task, _maintenance_worker_task, _boot_tasks
    _boot_tasks = []
    runtime_flags = api_runtime_flags()
    logger.info("API startup — runtime flags: %s", runtime_flags)
    _log_api_runtime_role(runtime_flags)
    _log_cors_settings()

    try:
        await ensure_runtime_schema_compatibility()
    except Exception:
        logger.exception("Runtime schema compatibility check failed")
        raise

    if runtime_flags["run_api_worker"]:
        from batch.worker import worker_loop
        _worker_task = asyncio.create_task(worker_loop(AsyncSessionLocal))
        _maintenance_worker_task = asyncio.create_task(_maintenance_worker_watchdog(AsyncSessionLocal))

    llm = None
    if runtime_flags["run_resume_worker"] or runtime_flags["run_archival_worker"]:
        llm = get_llm_client()

    if runtime_flags["run_resume_worker"]:
        from batch.resume_worker import recover_stuck_generation_tasks
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

    if runtime_flags["run_boot_scan"]:
        from batch.resume_worker import boot_scan

        async def _delayed_boot_scan():
            await asyncio.sleep(30)
            try:
                async with AsyncSessionLocal() as db:
                    await boot_scan(db)
            except Exception:
                logger.warning("Boot scan failed", exc_info=True)

        _boot_tasks.append(asyncio.create_task(_delayed_boot_scan()))

    if runtime_flags["run_boot_embed"]:
        from batch.worker import boot_embed_uncached_jobs

        async def _delayed_boot_embed():
            await asyncio.sleep(60)
            try:
                await boot_embed_uncached_jobs(AsyncSessionLocal)
            except Exception:
                logger.warning("Boot embed failed", exc_info=True)

        _boot_tasks.append(asyncio.create_task(_delayed_boot_embed()))

    if runtime_flags["run_archival_worker"]:
        from batch.archival_worker import recover_stuck_archival_tasks
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
    for t in (_worker_task, _resume_worker_task, _archival_worker_task, _maintenance_worker_task, *_boot_tasks):
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
    allow_origins=effective_allowed_origins(),
    allow_origin_regex=effective_allow_origin_regex(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(dev.router)
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


@app.exception_handler(ProgrammingError)
async def db_schema_exception_handler(request: Request, exc: ProgrammingError) -> JSONResponse:
    if not _looks_like_undefined_column_error(exc):
        logger.exception("Database programming error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    logger.warning(
        "Detected undefined-column database error on %s %s; attempting schema repair",
        request.method,
        request.url.path,
    )
    try:
        await _heal_schema_once()
    except Exception:
        logger.exception("Schema repair attempt failed after undefined-column error")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database schema is being repaired, retry shortly"},
        headers={"Retry-After": "2"},
    )


@app.exception_handler(SATimeoutError)
async def db_timeout_exception_handler(request: Request, exc: SATimeoutError) -> JSONResponse:
    logger.warning("Database pool timeout on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database busy, retry shortly"},
        headers={"Retry-After": "2"},
    )


@app.get("/health")
async def health():
    flags = api_runtime_flags()
    return {
        "status": "ok",
        "workers": {k: v for k, v in flags.items() if v},
    }


@app.get("/ready")
async def ready():
    try:
        db_url, connect_args = _parse_url(settings.database_url)
        ready_engine = create_async_engine(
            db_url,
            echo=False,
            connect_args=connect_args,
            poolclass=NullPool,
        )
        async with ready_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await ready_engine.dispose()
        return {"status": "ok", "db": "ok"}
    except Exception:
        logger.exception("Health check DB ping failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "db": "unreachable"},
        )
