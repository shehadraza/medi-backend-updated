import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index,
    Integer, JSON, String, Text, func, literal_column, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_ai_conversation_id_user"),
        Index("ix_ai_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    encrypted_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint("role IN ('system', 'user', 'assistant')", name="ck_ai_messages_role"),
        UniqueConstraint("id", "user_id", name="uq_ai_message_id_user"),
        Index("ix_ai_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_ai_messages_user_created", "user_id", "created_at"),
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["ai_conversations.id", "ai_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_ai_messages_conversation_owner",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AIMessageFeedback(Base):
    __tablename__ = "ai_message_feedback"
    __table_args__ = (
        CheckConstraint("rating IN ('helpful', 'not_helpful')", name="ck_ai_feedback_rating"),
        UniqueConstraint("user_id", "message_id", name="uq_ai_feedback_user_message"),
        ForeignKeyConstraint(
            ["message_id", "user_id"],
            ["ai_messages.id", "ai_messages.user_id"],
            ondelete="CASCADE",
            name="fk_ai_feedback_message_owner",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    encrypted_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeSource(Base):
    __tablename__ = "ai_knowledge_sources"
    __table_args__ = (
        CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="ck_ai_source_review_status"),
        Index("ix_ai_knowledge_sources_review_status", "review_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "ai_knowledge_documents"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'processing', 'ready', 'published', 'failed', 'archived')", name="ck_ai_document_status"),
        UniqueConstraint("source_id", "content_hash", name="uq_ai_document_source_hash"),
        Index("ix_ai_documents_source_status", "source_id", "status"),
        Index("ix_ai_doc_source_status_last_seen", "source_id", "status", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_knowledge_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="und", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeSyncState(Base):
    """Sanitized status for automated trusted source synchronization."""
    __tablename__ = "ai_knowledge_sync_state"
    __table_args__ = (Index("ix_ai_knowledge_sync_next", "next_sync_at"),)

    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_knowledge_sources.id", ondelete="CASCADE"), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    documents_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")


class KnowledgeChunk(Base):
    __tablename__ = "ai_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_ai_chunk_document_index"),
        Index(
            "ix_ai_knowledge_chunks_fts",
            func.to_tsvector(literal_column("'simple'"), literal_column("text")),
            postgresql_using="gin",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)



