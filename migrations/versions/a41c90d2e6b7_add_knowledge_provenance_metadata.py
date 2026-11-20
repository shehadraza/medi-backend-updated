"""add structured knowledge document provenance metadata

Revision ID: a41c90d2e6b7
Revises: e24b03a2dd71
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a41c90d2e6b7"
down_revision: Union[str, Sequence[str], None] = "e24b03a2dd71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_knowledge_documents", sa.Column("source_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_knowledge_documents", "source_metadata")
