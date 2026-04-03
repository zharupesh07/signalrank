"""add agentic match reports to job_results

Revision ID: a7b8c9d0e1f2
Revises: f9a1b2c3d4e5
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f9a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_results", sa.Column("fit_band", sa.String(length=50), nullable=True))
    op.add_column("job_results", sa.Column("confidence_band", sa.String(length=50), nullable=True))
    op.add_column("job_results", sa.Column("explanation_summary", sa.Text(), nullable=True))
    op.add_column("job_results", sa.Column("match_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("job_results", sa.Column("verification_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("job_results", "verification_report")
    op.drop_column("job_results", "match_report")
    op.drop_column("job_results", "explanation_summary")
    op.drop_column("job_results", "confidence_band")
    op.drop_column("job_results", "fit_band")
