"""add scrape query cache

Revision ID: fa2b3c4d5e6f
Revises: a7b8c9d0e1f2
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "fa2b3c4d5e6f"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scrape_query_cache",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=50), nullable=False),
        sa.Column("term_normalized", sa.String(length=255), nullable=False),
        sa.Column("location_normalized", sa.String(length=255), nullable=False),
        sa.Column("country_normalized", sa.String(length=100), nullable=False),
        sa.Column("hours_old", sa.Integer(), nullable=False),
        sa.Column("result_job_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "site",
            "term_normalized",
            "location_normalized",
            "country_normalized",
            "hours_old",
            name="uq_scrape_query_cache_key",
        ),
    )
    op.create_index(
        "ix_scrape_query_cache_fresh_until",
        "scrape_query_cache",
        ["provider", "site", "fresh_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scrape_query_cache_fresh_until", table_name="scrape_query_cache")
    op.drop_table("scrape_query_cache")
