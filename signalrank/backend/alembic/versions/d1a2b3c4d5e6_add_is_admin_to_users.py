"""add is_admin to users

Revision ID: d1a2b3c4d5e6
Revises: a9b1c2d3e4f5
Create Date: 2026-03-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "d1a2b3c4d5e6"
down_revision = "a9b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("users", "is_admin")
