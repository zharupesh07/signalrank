"""add job availability urls

Revision ID: 6c7d8e9f0a1b
Revises: 5b6c7d8e9f0a
Create Date: 2026-05-09 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "6c7d8e9f0a1b"
down_revision = "5b6c7d8e9f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs_raw",
        sa.Column(
            "availability_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs_raw", "availability_urls")
