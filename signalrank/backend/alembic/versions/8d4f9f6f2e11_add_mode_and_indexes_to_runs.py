"""add_mode_and_indexes_to_runs

Revision ID: 8d4f9f6f2e11
Revises: 6c40f07f922a
Create Date: 2026-04-01 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d4f9f6f2e11"
down_revision: Union[str, Sequence[str], None] = "6c40f07f922a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("mode", sa.String(length=20), nullable=True, server_default="quick"))
    op.execute(
        """
        UPDATE runs
        SET mode = COALESCE(NULLIF(progress->>'requested_mode', ''), 'quick')
        WHERE mode IS NULL
        """
    )
    op.alter_column("runs", "mode", nullable=False, server_default="quick")
    op.create_index("ix_runs_user_started", "runs", ["user_id", "started_at"], unique=False)
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)
    op.create_index("ix_runs_status_mode_started", "runs", ["status", "mode", "started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_runs_status_mode_started", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_user_started", table_name="runs")
    op.drop_column("runs", "mode")
