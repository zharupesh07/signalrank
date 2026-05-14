from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from api.config import api_runtime_flags, is_desktop_mode, settings
from api.database import get_db
from api.deps import get_current_user
from api.models import Profile, Run, User
from api.rate_limits import enforce_user_rate_limit
from api.routes.admin import require_admin
from batch.run_kinds import run_kind_from_flags, run_kind_from_progress, scrape_reason_from_progress
from batch.run_progress import progress_int, progress_str
from batch.worker import get_queue

router = APIRouter(prefix="/api/runs", tags=["runs"])
logger = logging.getLogger(__name__)
ACTIVE_RUN_STATUSES = ("pending", "claimed", "scraping", "ranking")

def _display_status(db_status: str) -> str:
    return "completed" if db_status == "success" else db_status


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _jobs_snapshot(progress: dict | None) -> dict | None:
    if not isinstance(progress, dict):
        return None
    cache = progress.get("jobs_cache")
    if not isinstance(cache, dict):
        return None
    default = cache.get("default")
    return default if isinstance(default, dict) else None

class RunResponse(BaseModel):
    id: str
    run_id: str
    status: str
    job_count: int | None = None
    scrape_count: int | None = None
    ranked_count: int | None = None
    visible_count: int | None = None
    corpus_count: int | None = None
    scored_count: int | None = None
    shown_count: int | None = None
    corpus_source: str | None = None
    progress: dict | None = None
    run_kind: str | None = None
    scrape_reason: str | None = None
    jobs_snapshot: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    executor_type: str | None = None


class TriggerRunRequest(BaseModel):
    mode: Literal["quick", "full"] = "quick"
    disable_scraping: bool = False
    executor_type: Literal["local", "cloud"] | None = None


async def _create_run(
    *,
    requested_mode: str,
    disable_scraping: bool,
    executor_type: str | None,
    current_user: User,
    db: AsyncSession,
) -> dict[str, str]:
    force_scrape = requested_mode == "full" and not disable_scraping
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.onboarding_complete:
        raise HTTPException(status_code=400, detail="Please complete onboarding before triggering a run")
    if not is_desktop_mode():
        await enforce_user_rate_limit(
            current_user.id,
            "refresh_jobs",
            limit=6,
            window_seconds=60 * 60,
        )

    active_runs_result = await db.execute(
        select(Run)
        .where(
            Run.user_id == current_user.id,
            Run.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(Run.started_at.desc())
    )
    active_runs = active_runs_result.scalars().all()
    if active_runs:
        existing_run = active_runs[0]
        if len(active_runs) >= settings.max_active_runs_per_user:
            logger.info(
                "Run request reused active run %s for user_id=%s because active run limit=%s was reached",
                existing_run.id,
                current_user.id,
                settings.max_active_runs_per_user,
            )
            return {"id": existing_run.id, "run_id": existing_run.id, "status": existing_run.status}

    if executor_type == "local" and not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Local executor requires admin")

    run = Run(
        user_id=current_user.id,
        status="pending",
        mode=requested_mode,
        trigger_source="manual",
        executor_type=executor_type,
        progress={
            "requested_mode": requested_mode,
            "force_scrape": force_scrape,
            "disable_scraping": disable_scraping,
            "run_kind": run_kind_from_flags(
                force_scrape=force_scrape,
                disable_scraping=disable_scraping,
            ),
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    logger.info(
        "Run %s created as pending in DB (mode=%s user_id=%s); awaiting worker claim",
        run.id,
        requested_mode,
        current_user.id,
    )
    return {"id": run.id, "run_id": run.id, "status": "pending"}


def _serialize_run(run: Run) -> RunResponse:
    status = _display_status(run.status)
    ranked_count = progress_int(run.progress, "scored_job_count")
    visible_count = progress_int(run.progress, "shown_job_count")
    return RunResponse(
        id=run.id,
        run_id=run.id,
        status=status,
        job_count=run.job_count,
        scrape_count=run.scrape_count,
        ranked_count=ranked_count,
        visible_count=visible_count,
        corpus_count=progress_int(run.progress, "corpus_job_count"),
        scored_count=ranked_count,
        shown_count=visible_count,
        corpus_source=progress_str(run.progress, "corpus_source"),
        progress=run.progress,
        run_kind=run_kind_from_progress(run.progress),
        scrape_reason=scrape_reason_from_progress(run.progress),
        jobs_snapshot=_jobs_snapshot(run.progress),
        error=run.error,
        started_at=_iso_utc(run.started_at),
        finished_at=_iso_utc(run.finished_at),
        executor_type=run.executor_type,
    )


@router.post("/trigger", status_code=202)
async def trigger_run(
    body: TriggerRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_mode = (body.mode if body else "quick")
    return await _create_run(
        requested_mode=requested_mode,
        disable_scraping=bool(body.disable_scraping) if body else False,
        executor_type=body.executor_type if body else None,
        current_user=current_user,
        db=db,
    )


@router.post("/rank-existing", status_code=202)
async def rank_existing_jobs(
    body: TriggerRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_mode = (body.mode if body else "quick")
    return await _create_run(
        requested_mode=requested_mode,
        disable_scraping=True,
        executor_type=body.executor_type if body else None,
        current_user=current_user,
        db=db,
    )


@router.get("/latest", response_model=RunResponse)
async def get_latest_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No runs found")
    return _serialize_run(run)


@router.get("", response_model=list[RunResponse])
async def list_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run)
        .where(Run.user_id == current_user.id)
        .where(Run.status == "success")
        .order_by(Run.started_at.desc())
        .limit(50)
    )
    runs = result.scalars().all()
    return [_serialize_run(r) for r in runs]


@router.get("/{run_id}/status", response_model=RunResponse)
async def get_run_status(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.id == run_id, Run.user_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run)


@router.post("/{run_id}/stop", status_code=200)
async def stop_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Run).where(Run.id == run_id, Run.user_id == current_user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Can only cancel runs that are pending, scraping, or ranking
    cancellable_statuses = {"pending", "claimed", "scraping", "ranking"}
    if run.status not in cancellable_statuses:
        return {"stopped": False, "status": run.status, "message": f"Run is already {run.status}"}

    original_status = run.status
    values = {"cancel_requested": True}
    if original_status == "pending":
        values.update({"status": "cancelled", "finished_at": datetime.now(timezone.utc)})
    await db.execute(update(Run).where(Run.id == run_id).values(**values))
    await db.commit()

    return {"stopped": True, "status": "cancelled" if original_status == "pending" else "cancelling"}
