"""add_scraper_config_to_profile

Revision ID: b45374de6e57
Revises: a9b1c2d3e4f5
Create Date: 2026-03-28 12:32:26.203619

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b45374de6e57'
down_revision: Union[str, Sequence[str], None] = 'a9b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('scraper_hours_old', sa.Integer(), nullable=True))
    op.add_column('profiles', sa.Column('scraper_max_terms', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'scraper_max_terms')
    op.drop_column('profiles', 'scraper_hours_old')
