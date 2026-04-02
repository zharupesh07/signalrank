"""add title_relevance_score to job_results

Revision ID: a3b4c5d6e7f8
Revises: 8d4f9f6f2e11
Create Date: 2026-04-02 12:00:00.000000

"""
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "8d4f9f6f2e11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE job_results ADD COLUMN IF NOT EXISTS title_relevance_score FLOAT"
    )


def downgrade() -> None:
    op.drop_column("job_results", "title_relevance_score")
