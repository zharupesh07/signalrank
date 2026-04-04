"""add_tracker_fields

Revision ID: a1b2c3d4e5f6
Revises: 4e689d8074f1
Create Date: 2026-03-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "4e689d8074f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS priority VARCHAR(10)")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS location_group VARCHAR(100)")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_date TIMESTAMPTZ")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS offer_lpa FLOAT")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS system_score FLOAT")
    op.execute("ALTER TABLE applications ADD COLUMN IF NOT EXISTS resume_match_pct FLOAT")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS target_lpa FLOAT")


def downgrade() -> None:
    op.drop_column("profiles", "target_lpa")
    op.drop_column("applications", "resume_match_pct")
    op.drop_column("applications", "system_score")
    op.drop_column("applications", "offer_lpa")
    op.drop_column("applications", "interview_date")
    op.drop_column("applications", "location_group")
    op.drop_column("applications", "priority")
