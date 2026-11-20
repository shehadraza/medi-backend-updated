
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_notifications_user_idempotency",
        ),
        Index(
            "ix_notifications_due",
            "status",
            "scheduled_at",
            "next_retry_at",
        ),
        Index(
            "ix_notifications_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    medication_log_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("medication_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # in_app, email, push
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    # medication_reminder, missed_dose, course_completion, general
    notification_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )

    # Encrypted notification title, body and metadata.
    encrypted_payload: Mapped[str] = mapped_column(
        Text, nullable=False
    )

    # pending, sending, sent, failed, cancelled
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Store only a sanitized, non-sensitive error summary.
    last_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
