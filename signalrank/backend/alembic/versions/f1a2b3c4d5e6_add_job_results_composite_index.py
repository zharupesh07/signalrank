"""add composite index on job_results(user_id, run_id, final_score)

Revision ID: f1a2b3c4d5e6
Revises: e2f3a4b5c6d7
Create Date: 2026-03-28 19:00:00.000000

"""
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_job_results_user_run_score",
        "job_results",
        ["user_id", "run_id", "final_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_results_user_run_score", table_name="job_results")
