import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HealthProfile(Base):
    __tablename__ = "health_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )

    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_version: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    profile_photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_personalization_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_personalization_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proactive_health_analysis_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    proactive_health_analysis_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    proactive_wellness_notifications_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    proactive_wellness_notifications_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
