import asyncio
import logging

from api.config import settings
from api.database import AsyncSessionLocal
from api.deps_llm import get_llm_client
from batch.archival_worker import archival_worker_loop, recover_stuck_archival_tasks
from batch.resume_worker import boot_scan, recover_stuck_generation_tasks, resume_worker_loop
from batch.worker import boot_embed_uncached_jobs, worker_loop

logger = logging.getLogger(__name__)


async def _resume_worker_watchdog(llm) -> None:
    while True:
        try:
            await resume_worker_loop(AsyncSessionLocal, llm)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Resume worker crashed — restarting in 10s")
            await asyncio.sleep(10)


async def _archival_worker_watchdog(llm) -> None:
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

    if settings.run_resume_worker or settings.run_archival_worker:
        llm = get_llm_client()

    if settings.run_api_worker:
        tasks.append(asyncio.create_task(worker_loop(AsyncSessionLocal)))

    if settings.run_resume_worker:
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_generation_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck generation task(s)", recovered)
        tasks.append(asyncio.create_task(_resume_worker_watchdog(llm)))

    if settings.run_archival_worker:
        async with AsyncSessionLocal() as db:
            recovered = await recover_stuck_archival_tasks(db)
            if recovered:
                logger.info("Recovered %d stuck archival task(s)", recovered)
        tasks.append(asyncio.create_task(_archival_worker_watchdog(llm)))

    if settings.run_boot_scan:
        async with AsyncSessionLocal() as db:
            await boot_scan(db)

    if settings.run_boot_embed:
        await boot_embed_uncached_jobs(AsyncSessionLocal)

    if not tasks:
        logger.warning("No worker tasks enabled; exiting")
        return

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
