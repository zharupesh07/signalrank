"""add job_results filter indexes for archived_by_llm and company_tier

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-04-02 13:00:00.000000

"""
from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jr_user_archived ON job_results(user_id, archived_by_llm)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jr_user_tier ON job_results(user_id, company_tier)"
    )


def downgrade() -> None:
    op.drop_index("ix_jr_user_archived", table_name="job_results")
    op.drop_index("ix_jr_user_tier", table_name="job_results")
