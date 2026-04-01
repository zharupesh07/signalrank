import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI

from api.config import worker_runtime_flags
from api.database import AsyncSessionLocal, ensure_runtime_schema_compatibility
from api.deps_llm import get_llm_client
from api.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

_health_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@_health_app.get("/healthz")
async def healthz():
    return {"status": "ok"}


async def _serve_health(port: int) -> None:
    config = uvicorn.Config(
        _health_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


def _log_worker_runtime_role(runtime_flags: dict[str, bool]) -> None:
    logger.info(
        "Worker role: queue_worker=%s resume_worker=%s archival_worker=%s boot_scan=%s boot_embed=%s",
        runtime_flags["run_api_worker"],
        runtime_flags["run_resume_worker"],
        runtime_flags["run_archival_worker"],
        runtime_flags["run_boot_scan"],
        runtime_flags["run_boot_embed"],
    )
    if runtime_flags["run_api_worker"]:
        logger.info("Queue worker enabled: this process will poll DB for pending runs")


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


async def main() -> None:
    tasks: list[asyncio.Task] = []
    llm = None
    runtime_flags = worker_runtime_flags()
    logger.info("Worker entrypoint starting with flags=%s", runtime_flags)
    _log_worker_runtime_role(runtime_flags)

    health_port = int(os.environ.get("PORT", "8001"))
    logger.info("Starting health server on port %d (enables Railway sleep-on-inactivity)", health_port)
    tasks.append(asyncio.create_task(_serve_health(health_port)))

    await ensure_runtime_schema_compatibility()

    if runtime_flags["run_resume_worker"] or runtime_flags["run_archival_worker"]:
        llm = get_llm_client()

    if runtime_flags["run_api_worker"]:
        from batch.worker import worker_loop
        logger.info("Starting queue worker")
        tasks.append(asyncio.create_task(worker_loop(AsyncSessionLocal)))

    if runtime_flags["run_resume_worker"]:
        from batch.resume_worker import recover_stuck_generation_tasks
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_generation_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck generation task(s)", recovered)
        logger.info("Starting resume worker")
        tasks.append(asyncio.create_task(_resume_worker_watchdog(AsyncSessionLocal, llm)))

    if runtime_flags["run_archival_worker"]:
        from batch.archival_worker import recover_stuck_archival_tasks
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_archival_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck archival task(s)", recovered)
        logger.info("Starting archival worker")
        tasks.append(asyncio.create_task(_archival_worker_watchdog(AsyncSessionLocal, llm)))

    if runtime_flags["run_boot_scan"]:
        from batch.resume_worker import boot_scan
        async with AsyncSessionLocal() as db:
            await boot_scan(db)

    if runtime_flags["run_boot_embed"]:
        from batch.worker import boot_embed_uncached_jobs
        await boot_embed_uncached_jobs(AsyncSessionLocal)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
