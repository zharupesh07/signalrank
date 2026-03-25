"""add recruiter enrichment columns

Revision ID: f8a2b3c4d5e6
Revises: e46774946a0f
Create Date: 2026-03-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e46774946a0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recruiters", sa.Column("title", sa.String(255), nullable=True))
    op.add_column("recruiters", sa.Column("confidence", sa.String(20), nullable=True))
    op.add_column("recruiters", sa.Column("email_source", sa.String(50), nullable=True))
    op.add_column("recruiters", sa.Column("email_verified", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("recruiters", "email_verified")
    op.drop_column("recruiters", "email_source")
    op.drop_column("recruiters", "confidence")
    op.drop_column("recruiters", "title")
