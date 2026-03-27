"""add index on jobs_raw.ingested_at for recency filtering

Revision ID: a9b1c2d3e4f5
Revises: e701363301d5
Create Date: 2026-03-28

"""
from alembic import op

revision = "a9b1c2d3e4f5"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_jobs_raw_ingested_at", "jobs_raw", ["ingested_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_raw_ingested_at", table_name="jobs_raw")
