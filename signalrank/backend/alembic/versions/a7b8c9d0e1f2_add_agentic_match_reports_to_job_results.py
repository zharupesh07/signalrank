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
    op.execute("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS fit_band VARCHAR(50)")
    op.execute("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS confidence_band VARCHAR(50)")
    op.execute("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS explanation_summary TEXT")
    op.execute("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS match_report JSONB")
    op.execute("ALTER TABLE job_results ADD COLUMN IF NOT EXISTS verification_report JSONB")


def downgrade() -> None:
    op.drop_column("job_results", "verification_report")
    op.drop_column("job_results", "match_report")
    op.drop_column("job_results", "explanation_summary")
    op.drop_column("job_results", "confidence_band")
    op.drop_column("job_results", "fit_band")
