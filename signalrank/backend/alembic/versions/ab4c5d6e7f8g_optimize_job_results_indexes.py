"""optimize job_results indexes for list_jobs query performance

Revision ID: ab4c5d6e7f8g
Revises: fa2b3c4d5e6f
Create Date: 2026-04-04 15:00:00.000000

"""
from alembic import op

revision = "ab4c5d6e7f8g"
down_revision = "fa2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add composite index for main list_jobs query with final_score sort
    # This index helps filter by user_id and order by final_score efficiently
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jr_user_final_score_job ON job_results(user_id, final_score DESC, job_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_jr_user_final_score_job", table_name="job_results")
