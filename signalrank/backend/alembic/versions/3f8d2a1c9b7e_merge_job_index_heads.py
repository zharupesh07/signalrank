"""merge job index heads

Revision ID: 3f8d2a1c9b7e
Revises: ab4c5d6e7f8g, d2e3f4a5b6c7
Create Date: 2026-04-04 20:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

# revision identifiers, used by Alembic.
revision: str = "3f8d2a1c9b7e"
down_revision: Union[str, Sequence[str], None] = ("ab4c5d6e7f8g", "d2e3f4a5b6c7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
