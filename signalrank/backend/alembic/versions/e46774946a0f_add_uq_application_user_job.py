"""add_uq_application_user_job

Revision ID: e46774946a0f
Revises: 90e3a061d643
Create Date: 2026-03-24 21:27:34.284864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e46774946a0f'
down_revision: Union[str, Sequence[str], None] = '90e3a061d643'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint("uq_application_user_job", "applications", ["user_id", "job_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_application_user_job", "applications", type_="unique")
