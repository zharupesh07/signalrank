"""merge_heads

Revision ID: 6c40f07f922a
Revises: 2303d3bbc034, af91c2d4e5f7
Create Date: 2026-03-30 16:48:26.935786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c40f07f922a'
down_revision: Union[str, Sequence[str], None] = ('2303d3bbc034', 'af91c2d4e5f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
