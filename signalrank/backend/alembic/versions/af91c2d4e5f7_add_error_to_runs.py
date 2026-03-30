"""add_error_to_runs

Revision ID: af91c2d4e5f7
Revises: e701363301d5
Create Date: 2026-03-29 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "af91c2d4e5f7"
down_revision: Union[str, Sequence[str], None] = "e701363301d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT")


def downgrade() -> None:
    op.drop_column("runs", "error")
