"""hnsw index on jobs_raw.embedding for ANN pre-filter

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-03
"""

from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW index for approximate nearest-neighbour search on job embeddings.
    # Used by the ANN pre-filter to reduce ranking candidates from 2000 → ~300
    # before full scoring. Only indexes rows where embedding IS NOT NULL.
    # CREATE INDEX CONCURRENTLY requires running outside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_jobs_raw_embedding_hnsw
            ON jobs_raw
            USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_raw_embedding_hnsw")
