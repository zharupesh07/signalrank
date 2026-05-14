from sqlalchemy.ext.asyncio import AsyncSession

from api.models import JobResult
from api.sql_compat import conflict_kwargs, dialect_insert


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
    def _upsert(batch: list[dict]):
        stmt = dialect_insert(db, JobResult).values(batch)
        return stmt.on_conflict_do_update(
            **conflict_kwargs(db, constraint="uq_job_results_user_job"),
            set_={
                "run_id": stmt.excluded.run_id,
                "semantic_score": stmt.excluded.semantic_score,
                "skills_score": stmt.excluded.skills_score,
                "company_score": stmt.excluded.company_score,
                "seniority_score": stmt.excluded.seniority_score,
                "location_score": stmt.excluded.location_score,
                "recency_score": stmt.excluded.recency_score,
                "final_score": stmt.excluded.final_score,
                "title_relevance_score": stmt.excluded.title_relevance_score,
                "fit_band": stmt.excluded.fit_band,
                "confidence_band": stmt.excluded.confidence_band,
                "explanation_summary": stmt.excluded.explanation_summary,
                "match_report": stmt.excluded.match_report,
                "verification_report": stmt.excluded.verification_report,
                "company_tier": stmt.excluded.company_tier,
                "is_contract": stmt.excluded.is_contract,
            },
        )

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
            await db.execute(_upsert(insert_batch))
            insert_batch.clear()
    if insert_batch:
        await db.execute(_upsert(insert_batch))
    await db.commit()
