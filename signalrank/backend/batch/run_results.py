from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobResult


def normalize_ranked_df(ranked_df):
    if "seniority_score_dim" in ranked_df.columns and "seniority_score" not in ranked_df.columns:
        return ranked_df.rename(columns={"seniority_score_dim": "seniority_score"})
    return ranked_df


async def persist_ranked_results(
    db: AsyncSession,
    *,
    ranked_df,
    run_id: str,
    user_id: str,
) -> None:
    insert_batch: list[dict] = []
    for row in ranked_df.itertuples(index=False):
        insert_batch.append({
            "run_id": run_id,
            "user_id": user_id,
            "job_id": row.id,
            "semantic_score": float(row.semantic_score or 0),
            "skills_score": float(row.skills_score or 0),
            "company_score": float(row.company_score or 0),
            "seniority_score": float(row.seniority_score or 0),
            "location_score": float(row.location_score or 0),
            "recency_score": float(row.recency_score or 0),
            "final_score": float(row.final_score or 0),
            "title_relevance_score": float(getattr(row, "title_relevance_score", None) or 0),
            "fit_band": getattr(row, "fit_band", None),
            "confidence_band": getattr(row, "confidence_band", None),
            "explanation_summary": getattr(row, "explanation_summary", None),
            "match_report": getattr(row, "match_report", None),
            "verification_report": getattr(row, "verification_report", None),
            "company_tier": str(row.company_tier or ""),
            "is_contract": bool(row.is_contract),
        })
        if len(insert_batch) >= 500:
            await db.execute(
                pg_insert(JobResult).values(insert_batch).on_conflict_do_update(
                    constraint="uq_job_results_user_job",
                    set_={
                        "run_id": pg_insert(JobResult).excluded.run_id,
                        "semantic_score": pg_insert(JobResult).excluded.semantic_score,
                        "skills_score": pg_insert(JobResult).excluded.skills_score,
                        "company_score": pg_insert(JobResult).excluded.company_score,
                        "seniority_score": pg_insert(JobResult).excluded.seniority_score,
                        "location_score": pg_insert(JobResult).excluded.location_score,
                        "recency_score": pg_insert(JobResult).excluded.recency_score,
                        "final_score": pg_insert(JobResult).excluded.final_score,
                        "title_relevance_score": pg_insert(JobResult).excluded.title_relevance_score,
                        "fit_band": pg_insert(JobResult).excluded.fit_band,
                        "confidence_band": pg_insert(JobResult).excluded.confidence_band,
                        "explanation_summary": pg_insert(JobResult).excluded.explanation_summary,
                        "match_report": pg_insert(JobResult).excluded.match_report,
                        "verification_report": pg_insert(JobResult).excluded.verification_report,
                        "company_tier": pg_insert(JobResult).excluded.company_tier,
                        "is_contract": pg_insert(JobResult).excluded.is_contract,
                    },
                )
            )
            insert_batch.clear()
    if insert_batch:
        await db.execute(
            pg_insert(JobResult).values(insert_batch).on_conflict_do_update(
                constraint="uq_job_results_user_job",
                set_={
                    "run_id": pg_insert(JobResult).excluded.run_id,
                    "semantic_score": pg_insert(JobResult).excluded.semantic_score,
                    "skills_score": pg_insert(JobResult).excluded.skills_score,
                    "company_score": pg_insert(JobResult).excluded.company_score,
                    "seniority_score": pg_insert(JobResult).excluded.seniority_score,
                    "location_score": pg_insert(JobResult).excluded.location_score,
                    "recency_score": pg_insert(JobResult).excluded.recency_score,
                    "final_score": pg_insert(JobResult).excluded.final_score,
                    "title_relevance_score": pg_insert(JobResult).excluded.title_relevance_score,
                    "fit_band": pg_insert(JobResult).excluded.fit_band,
                    "confidence_band": pg_insert(JobResult).excluded.confidence_band,
                    "explanation_summary": pg_insert(JobResult).excluded.explanation_summary,
                    "match_report": pg_insert(JobResult).excluded.match_report,
                    "verification_report": pg_insert(JobResult).excluded.verification_report,
                    "company_tier": pg_insert(JobResult).excluded.company_tier,
                    "is_contract": pg_insert(JobResult).excluded.is_contract,
                },
            )
        )
    await db.commit()
