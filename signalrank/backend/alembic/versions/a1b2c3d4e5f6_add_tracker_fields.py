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
    op.add_column("applications", sa.Column("priority", sa.String(10), nullable=True))
    op.add_column("applications", sa.Column("location_group", sa.String(100), nullable=True))
    op.add_column("applications", sa.Column("interview_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("offer_lpa", sa.Float(), nullable=True))
    op.add_column("applications", sa.Column("system_score", sa.Float(), nullable=True))
    op.add_column("applications", sa.Column("resume_match_pct", sa.Float(), nullable=True))
    op.add_column("profiles", sa.Column("target_lpa", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "target_lpa")
    op.drop_column("applications", "resume_match_pct")
    op.drop_column("applications", "system_score")
    op.drop_column("applications", "offer_lpa")
    op.drop_column("applications", "interview_date")
    op.drop_column("applications", "location_group")
    op.drop_column("applications", "priority")
