"""add notification read timestamp

Revision ID: 3dedcae0e8fe
Revises: 01dfd8655b57
Create Date: 2026-11-17 21:51:34.405768

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3dedcae0e8fe'
down_revision: Union[str, Sequence[str], None] = '01dfd8655b57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "read_at")