from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func


def dialect_name(db: AsyncSession) -> str:
    return db.get_bind().dialect.name


def dialect_insert(db: AsyncSession, model):
    if dialect_name(db) == "sqlite":
        return sqlite_insert(model)
    return pg_insert(model)


def text_prefix_expr(db: AsyncSession, column, length: int):
    if dialect_name(db) == "sqlite":
        return func.substr(column, 1, length)
    return func.left(column, length)


def conflict_kwargs(db: AsyncSession, *, constraint: str | None = None, index_elements=None):
    if dialect_name(db) == "sqlite":
        if index_elements is not None:
            return {"index_elements": index_elements}
        constraint_map = {
            "uq_job_results_user_job": ["user_id", "job_id"],
            "uq_generation_queue_user_job": ["user_id", "job_id"],
            "uq_archival_queue_user_job_result": ["user_id", "job_result_id"],
            "uq_recruiter_company_linkedin": ["company", "linkedin_url"],
            "uq_application_user_job": ["user_id", "job_id"],
            "uq_embedding_text_cfg": ["text_fp", "cfg_fp"],
            "uq_tailored_resume_user_job": ["user_id", "job_id"],
        }
        mapped = conflict_map_get(constraint_map, constraint)
        return {"index_elements": mapped} if mapped else {}
    if constraint:
        return {"constraint": constraint}
    return {"index_elements": index_elements}


def conflict_map_get(mapping: dict[str, list[str]], key: str | None) -> list[str] | None:
    if key is None:
        return None
    return mapping.get(key)
