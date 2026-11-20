"""Encrypted user-reported daily wellness check-ins."""

from datetime import date, datetime, timezone
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyHealthCheckIn(Base):
    __tablename__ = "daily_health_checkins"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_daily_health_checkins_user_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
