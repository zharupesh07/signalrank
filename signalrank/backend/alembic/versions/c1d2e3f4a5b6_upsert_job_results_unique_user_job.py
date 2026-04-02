"""upsert job_results: unique (user_id, job_id)

Revision ID: c1d2e3f4a5b6
Revises: b4c5d6e7f8a9
Create Date: 2026-04-03

Changes:
- Deduplicate job_results keeping best final_score per (user_id, job_id)
- Add UNIQUE constraint (user_id, job_id) — enables upsert on each run
- Replace ix_job_results_user_run_score with ix_job_results_user_score
"""

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Delete duplicate rows, keeping the one with the highest final_score per (user_id, job_id).
    #    On tie, keep the most recently inserted row (highest ctid).
    op.execute("""
        DELETE FROM job_results
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, job_id) id
            FROM job_results
            ORDER BY user_id, job_id, final_score DESC NULLS LAST, ctid DESC
        )
    """)

    # 2. Add unique constraint.
    op.create_unique_constraint("uq_job_results_user_job", "job_results", ["user_id", "job_id"])

    # 3. Replace old index (included run_id, no longer the query pattern) with leaner one.
    op.drop_index("ix_job_results_user_run_score", table_name="job_results", if_exists=True)
    op.create_index("ix_job_results_user_score", "job_results", ["user_id", "final_score"])


def downgrade() -> None:
    op.drop_index("ix_job_results_user_score", table_name="job_results")
    op.create_index("ix_job_results_user_run_score", "job_results", ["user_id", "run_id", "final_score"])
    op.drop_constraint("uq_job_results_user_job", "job_results", type_="unique")
