"""add job preference memory

Revision ID: 5b6c7d8e9f0a
Revises: 4972000b8cc0
Create Date: 2026-04-13 01:35:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "5b6c7d8e9f0a"
down_revision = "4972000b8cc0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_preference_memory",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("state_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("last_feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "job_feedback_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("quick_actions", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column("job_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column("job_snapshots", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column("extracted_delta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("session_context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_feedback_events_user_created", "job_feedback_events", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_job_feedback_events_run_id"), "job_feedback_events", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_feedback_events_run_id"), table_name="job_feedback_events")
    op.drop_index("ix_job_feedback_events_user_created", table_name="job_feedback_events")
    op.drop_table("job_feedback_events")
    op.drop_table("job_preference_memory")
