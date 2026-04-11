from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobRaw, JobResult, Run


async def load_rerank_corpus_job_urls(
    db: AsyncSession,
    *,
    user_id: str,
    mode: str,
    exclude_run_id: str,
) -> tuple[list[str], dict[str, str | int] | None]:
    preferred_run = (
        await db.execute(
            select(Run)
            .where(
                Run.user_id == user_id,
                Run.status == "success",
                Run.scrape_count.is_not(None),
                Run.scrape_count > 0,
                Run.mode == mode,
                Run.id != exclude_run_id,
            )
            .order_by(Run.finished_at.desc().nullslast(), Run.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    source_run = preferred_run
    if source_run is None:
        source_run = (
            await db.execute(
                select(Run)
                .where(
                    Run.user_id == user_id,
                    Run.status == "success",
                    Run.scrape_count.is_not(None),
                    Run.scrape_count > 0,
                    Run.id != exclude_run_id,
                )
                .order_by(Run.finished_at.desc().nullslast(), Run.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if source_run is not None:
        url_rows = await db.execute(
            select(JobRaw.job_url)
            .join(JobResult, JobResult.job_id == JobRaw.id)
            .where(JobResult.run_id == source_run.id)
            .order_by(JobResult.final_score.desc().nullslast(), JobRaw.ingested_at.desc())
        )
        job_urls = []
        seen_urls: set[str] = set()
        for (job_url,) in url_rows.all():
            if job_url and job_url not in seen_urls:
                seen_urls.add(job_url)
                job_urls.append(job_url)
        if job_urls:
            return job_urls, {
                "corpus_source": "latest_scrape_run",
                "corpus_run_id": str(source_run.id),
                "corpus_job_count": len(job_urls),
            }

    fallback_rows = await db.execute(
        select(JobRaw.job_url)
        .join(JobResult, JobResult.job_id == JobRaw.id)
        .where(JobResult.user_id == user_id)
        .order_by(JobResult.final_score.desc().nullslast(), JobRaw.ingested_at.desc())
    )
    fallback_urls = []
    seen_urls: set[str] = set()
    for (job_url,) in fallback_rows.all():
        if job_url and job_url not in seen_urls:
            seen_urls.add(job_url)
            fallback_urls.append(job_url)
    if fallback_urls:
        return fallback_urls, {
            "corpus_source": "user_job_results",
            "corpus_job_count": len(fallback_urls),
        }

    return [], None
