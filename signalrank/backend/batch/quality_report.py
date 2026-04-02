from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Application, JobResult, Run, User
from domain.quality_metrics import compute_metrics


# Application statuses that indicate positive signal (user was interested)
_APPLIED_STATUSES = {"interested", "applied", "interviewing", "offer", "accepted"}
# Application statuses that indicate explicit rejection/skip
_SKIPPED_STATUSES = {"rejected", "withdrawn", "archived"}


async def compute_user_quality_metrics(db: AsyncSession, user_id: str, k: int = 10) -> dict:
    """Compute ranking quality metrics for a single user.

    Uses the latest completed run's job_results as the ranked list,
    correlated with that user's application decisions.
    """
    latest_run = (
        await db.execute(
            select(Run)
            .where(Run.user_id == user_id, Run.status == "done")
            .order_by(Run.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not latest_run:
        return {"user_id": user_id, "error": "no completed runs"}

    ranked_rows = (
        await db.execute(
            select(JobResult.job_id, JobResult.final_score)
            .where(JobResult.run_id == latest_run.id, JobResult.user_id == user_id)
            .order_by(JobResult.final_score.desc().nullslast())
        )
    ).all()
    ranked_job_ids = [str(r.job_id) for r in ranked_rows]

    apps = (
        await db.execute(
            select(Application.job_id, Application.status)
            .where(Application.user_id == user_id, Application.job_id.is_not(None))
        )
    ).all()

    applied_job_ids = [str(a.job_id) for a in apps if a.status in _APPLIED_STATUSES]
    skipped_job_ids = [str(a.job_id) for a in apps if a.status in _SKIPPED_STATUSES]

    metrics = compute_metrics(
        applied_job_ids=applied_job_ids,
        skipped_job_ids=skipped_job_ids,
        ranked_job_ids=ranked_job_ids,
        k=k,
    )
    return {
        "user_id": user_id,
        "run_id": latest_run.id,
        "run_finished_at": str(latest_run.finished_at) if latest_run.finished_at else None,
        **metrics,
    }


async def compute_global_quality_metrics(db: AsyncSession, k: int = 10) -> dict:
    """Aggregate quality metrics across all users who have completed runs."""
    users_result = await db.execute(
        select(User.id).where(
            User.id.in_(select(Run.user_id).where(Run.status == "done").distinct())
        )
    )
    user_ids = [r.id for r in users_result.all()]

    if not user_ids:
        return {"error": "no users with completed runs", "user_count": 0}

    per_user = []
    for user_id in user_ids:
        metrics = await compute_user_quality_metrics(db, user_id, k=k)
        if "error" not in metrics:
            per_user.append(metrics)

    if not per_user:
        return {"error": "no valid metrics", "user_count": 0}

    def _avg(field: str) -> float:
        vals = [m[field] for m in per_user if m.get(field) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "user_count": len(per_user),
        "k": k,
        "avg_precision_at_k": _avg("precision_at_k"),
        "avg_ndcg": _avg("ndcg"),
        "avg_ndcg_at_k": _avg("ndcg_at_k"),
        "avg_skip_rate_at_k": _avg("skip_rate_at_k"),
        "per_user": per_user,
    }
