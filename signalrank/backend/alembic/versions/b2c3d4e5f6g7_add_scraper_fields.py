"""add scraper fields

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("custom_search_queries", JSONB, nullable=True))
    op.add_column("runs", sa.Column("scrape_count", sa.Integer, nullable=True))
    op.add_column("runs", sa.Column("progress", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "progress")
    op.drop_column("runs", "scrape_count")
    op.drop_column("profiles", "custom_search_queries")
