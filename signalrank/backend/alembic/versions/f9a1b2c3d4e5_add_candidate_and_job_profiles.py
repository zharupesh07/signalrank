"""add candidate_profile and job_profile JSON artifacts

Revision ID: f9a1b2c3d4e5
Revises: c1d2e3f4a5b6
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f9a1b2c3d4e5"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS candidate_profile JSONB"
    )
    op.execute(
        "ALTER TABLE jobs_raw ADD COLUMN IF NOT EXISTS job_profile JSONB"
    )


def downgrade() -> None:
    op.drop_column("jobs_raw", "job_profile")
    op.drop_column("profiles", "candidate_profile")
