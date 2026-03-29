import asyncio
import logging

from api.config import worker_runtime_flags
from api.database import AsyncSessionLocal, ensure_runtime_schema_compatibility
from api.deps_llm import get_llm_client

logger = logging.getLogger(__name__)


async def _resume_worker_watchdog(llm) -> None:
    from batch.resume_worker import resume_worker_loop

    while True:
        try:
            await resume_worker_loop(AsyncSessionLocal, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resume worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _archival_worker_watchdog(llm) -> None:
    from batch.archival_worker import archival_worker_loop

    while True:
        try:
            await archival_worker_loop(AsyncSessionLocal, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Archival worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def main() -> None:
    tasks: list[asyncio.Task] = []
    llm = None
    runtime_flags = worker_runtime_flags()

    await ensure_runtime_schema_compatibility()

    if runtime_flags["run_resume_worker"] or runtime_flags["run_archival_worker"]:
        llm = get_llm_client()

    if runtime_flags["run_api_worker"]:
        from batch.worker import worker_loop
        tasks.append(asyncio.create_task(worker_loop(AsyncSessionLocal)))

    if runtime_flags["run_resume_worker"]:
        from batch.resume_worker import recover_stuck_generation_tasks
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_generation_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck generation task(s)", recovered)
        tasks.append(asyncio.create_task(_resume_worker_watchdog(llm)))

    if runtime_flags["run_archival_worker"]:
        from batch.archival_worker import recover_stuck_archival_tasks
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_archival_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck archival task(s)", recovered)
        tasks.append(asyncio.create_task(_archival_worker_watchdog(llm)))

    if runtime_flags["run_boot_scan"]:
        from batch.resume_worker import boot_scan
        async with AsyncSessionLocal() as db:
            await boot_scan(db)

    if runtime_flags["run_boot_embed"]:
        from batch.worker import boot_embed_uncached_jobs
        await boot_embed_uncached_jobs(AsyncSessionLocal)

    if not tasks:
        logger.warning("No worker tasks enabled; exiting")
        return

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
