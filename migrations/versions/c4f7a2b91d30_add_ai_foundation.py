"""add AI conversations and knowledge foundation

Revision ID: c4f7a2b91d30
Revises: bd6f0a095d07
Create Date: 2026-11-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f7a2b91d30"
down_revision: Union[str, Sequence[str], None] = "bd6f0a095d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("encrypted_title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ai_conversation_id_user"),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_index("ix_ai_conversations_user_updated", "ai_conversations", ["user_id", "updated_at"])

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('system', 'user', 'assistant')", name="ck_ai_messages_role"),
        sa.ForeignKeyConstraint(["conversation_id", "user_id"], ["ai_conversations.id", "ai_conversations.user_id"], ondelete="CASCADE", name="fk_ai_messages_conversation_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ai_message_id_user"),
    )
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])
    op.create_index("ix_ai_messages_user_id", "ai_messages", ["user_id"])
    op.create_index("ix_ai_messages_conversation_created", "ai_messages", ["conversation_id", "created_at"])
    op.create_index("ix_ai_messages_user_created", "ai_messages", ["user_id", "created_at"])

    op.create_table(
        "ai_message_feedback",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column("encrypted_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating IN ('helpful', 'not_helpful')", name="ck_ai_feedback_rating"),
        sa.ForeignKeyConstraint(["message_id", "user_id"], ["ai_messages.id", "ai_messages.user_id"], ondelete="CASCADE", name="fk_ai_feedback_message_owner"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "message_id", name="uq_ai_feedback_user_message"),
    )
    op.create_index("ix_ai_message_feedback_message_id", "ai_message_feedback", ["message_id"])
    op.create_index("ix_ai_message_feedback_user_id", "ai_message_feedback", ["user_id"])

    op.create_table(
        "ai_knowledge_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="ck_ai_source_review_status"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_knowledge_sources_review_status", "ai_knowledge_sources", ["review_status"])

    op.create_table(
        "ai_knowledge_documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'processing', 'ready', 'published', 'failed', 'archived')", name="ck_ai_document_status"),
        sa.ForeignKeyConstraint(["source_id"], ["ai_knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_ai_document_source_hash"),
    )
    op.create_index("ix_ai_knowledge_documents_source_id", "ai_knowledge_documents", ["source_id"])
    op.create_index("ix_ai_documents_source_status", "ai_knowledge_documents", ["source_id", "status"])

    op.create_table(
        "ai_knowledge_chunks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_provider", sa.String(80), nullable=True),
        sa.Column("embedding_model", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["ai_knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_ai_chunk_document_index"),
    )
    op.create_index("ix_ai_knowledge_chunks_document_id", "ai_knowledge_chunks", ["document_id"])
    op.execute("CREATE INDEX ix_ai_knowledge_chunks_fts ON ai_knowledge_chunks USING GIN (to_tsvector('simple', text))")


def downgrade() -> None:
    op.drop_index("ix_ai_knowledge_chunks_fts", table_name="ai_knowledge_chunks")
    op.drop_index("ix_ai_knowledge_chunks_document_id", table_name="ai_knowledge_chunks")
    op.drop_table("ai_knowledge_chunks")
    op.drop_index("ix_ai_documents_source_status", table_name="ai_knowledge_documents")
    op.drop_index("ix_ai_knowledge_documents_source_id", table_name="ai_knowledge_documents")
    op.drop_table("ai_knowledge_documents")
    op.drop_index("ix_ai_knowledge_sources_review_status", table_name="ai_knowledge_sources")
    op.drop_table("ai_knowledge_sources")
    op.drop_index("ix_ai_message_feedback_user_id", table_name="ai_message_feedback")
    op.drop_index("ix_ai_message_feedback_message_id", table_name="ai_message_feedback")
    op.drop_table("ai_message_feedback")
    op.drop_index("ix_ai_messages_user_created", table_name="ai_messages")
    op.drop_index("ix_ai_messages_conversation_created", table_name="ai_messages")
    op.drop_index("ix_ai_messages_user_id", table_name="ai_messages")
    op.drop_index("ix_ai_messages_conversation_id", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_conversations_user_updated", table_name="ai_conversations")
    op.drop_index("ix_ai_conversations_user_id", table_name="ai_conversations")
    op.drop_table("ai_conversations")
