"""add role_clusters to jobs_raw

Revision ID: e2f3a4b5c6d7
Revises: d1a2b3c4d5e6
Create Date: 2026-03-28 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e2f3a4b5c6d7"
down_revision = ("d1a2b3c4d5e6", "b45374de6e57")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs_raw ADD COLUMN IF NOT EXISTS role_clusters JSONB DEFAULT '[]'::jsonb")
    op.create_index(
        "ix_jobs_raw_role_clusters",
        "jobs_raw",
        ["role_clusters"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_raw_role_clusters", table_name="jobs_raw")
    op.drop_column("jobs_raw", "role_clusters")
