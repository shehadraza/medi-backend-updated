"""add automated knowledge sync metadata

Revision ID: d1a3f48c6e20
Revises: c4f7a2b91d30, cb8fe1124ce2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1a3f48c6e20"
down_revision: Union[str, Sequence[str], None] = ("c4f7a2b91d30", "cb8fe1124ce2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_knowledge_documents", sa.Column("source_url", sa.String(1000), nullable=True))
    op.add_column("ai_knowledge_documents", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "ai_knowledge_sync_state",
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("documents_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["source_id"], ["ai_knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index("ix_ai_knowledge_sync_next", "ai_knowledge_sync_state", ["next_sync_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_knowledge_sync_next", table_name="ai_knowledge_sync_state")
    op.drop_table("ai_knowledge_sync_state")
    op.drop_column("ai_knowledge_documents", "published_at")
    op.drop_column("ai_knowledge_documents", "source_url")
