"""add knowledge sync lifecycle and retry metadata

Revision ID: e24b03a2dd71
Revises: d1a3f48c6e20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e24b03a2dd71"
down_revision: Union[str, Sequence[str], None] = "d1a3f48c6e20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_knowledge_documents", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_knowledge_documents", sa.Column("metadata_history", sa.JSON(), nullable=True))
    op.create_index("ix_ai_doc_source_status_last_seen", "ai_knowledge_documents", ["source_id", "status", "last_seen_at"])
    op.add_column("ai_knowledge_sync_state", sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("ai_knowledge_sync_state", "failure_count")
    op.drop_index("ix_ai_doc_source_status_last_seen", table_name="ai_knowledge_documents")
    op.drop_column("ai_knowledge_documents", "metadata_history")
    op.drop_column("ai_knowledge_documents", "last_seen_at")
