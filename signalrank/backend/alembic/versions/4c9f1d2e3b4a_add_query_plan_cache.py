"""add query_plan_cache

Revision ID: 4c9f1d2e3b4a
Revises: 3f8d2a1c9b7e
Create Date: 2026-04-04 20:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4c9f1d2e3b4a"
down_revision = "3f8d2a1c9b7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_plan_cache",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False, unique=True),
        sa.Column("profile_fingerprint", sa.Text(), nullable=False),
        sa.Column("search_window_days", sa.Integer(), nullable=False),
        sa.Column("source_filter", sa.Text(), nullable=False),
        sa.Column("query_version", sa.String(length=100), nullable=False),
        sa.Column("max_terms", sa.Integer(), nullable=False),
        sa.Column("query_payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_query_plan_cache_profile_window",
        "query_plan_cache",
        ["profile_fingerprint", "search_window_days"],
    )
    op.create_index(
        "ix_query_plan_cache_source_filter",
        "query_plan_cache",
        ["source_filter"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_plan_cache_source_filter", table_name="query_plan_cache")
    op.drop_index("ix_query_plan_cache_profile_window", table_name="query_plan_cache")
    op.drop_table("query_plan_cache")
