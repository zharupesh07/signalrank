"""add archival queue and fields

Revision ID: c7d8e9f0a1b2
Revises: f8a2b3c4d5e6
Create Date: 2026-03-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "f8a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_results", sa.Column("archived_by_llm", sa.Boolean(), nullable=True))
    op.add_column("job_results", sa.Column("archival_reason", sa.String(500), nullable=True))

    op.create_table(
        "archival_queue",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("job_result_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_result_id"], ["job_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "job_result_id", name="uq_archival_queue_user_job_result"),
    )


def downgrade() -> None:
    op.drop_table("archival_queue")
    op.drop_column("job_results", "archival_reason")
    op.drop_column("job_results", "archived_by_llm")
