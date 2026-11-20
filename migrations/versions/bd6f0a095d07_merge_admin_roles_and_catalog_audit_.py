"""merge admin roles and catalog audit heads

Revision ID: bd6f0a095d07
Revises: 7bf05ad838d6, a91f62c4d810
Create Date: 2026-11-18 18:36:24.683467

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd6f0a095d07'
down_revision: Union[str, Sequence[str], None] = ('7bf05ad838d6', 'a91f62c4d810')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
