
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
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


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # OCR and extracted clinical information must be encrypted.
    encrypted_ocr_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), default="uploaded", nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        onupdate=utc_now, nullable=False
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    prescription_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Contains extracted medicine name, dosage, frequency,
    # duration and instructions. Keep encrypted until user confirms.
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)

    verification_status: Mapped[str] = mapped_column(
        String(30), default="needs_review", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Medication(Base):
    __tablename__ = "medications"
    __table_args__ = (
        UniqueConstraint(
            "prescription_item_id",
            name="uq_medications_prescription_item",
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
    prescription_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prescriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prescription_item_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prescription_items.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Medicine name, dosage, instructions and related clinical
    # details are stored as encrypted JSON.
    encrypted_data: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        onupdate=utc_now, nullable=False
    )


class MedicationSchedule(Base):
    __tablename__ = "medication_schedules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    medication_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Store dose instructions and recurrence details encrypted.
    encrypted_schedule: Mapped[str] = mapped_column(Text, nullable=False)

    next_dose_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
        onupdate=utc_now, nullable=False
    )


class MedicationLog(Base):
    __tablename__ = "medication_logs"
    __table_args__ = (
    UniqueConstraint(
        "schedule_id",
        "scheduled_at",
        name="uq_medication_log_schedule_dose",
    ),
)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    medication_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("medication_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    taken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


Index(
    "ix_medication_logs_user_scheduled",
    MedicationLog.user_id,
    MedicationLog.scheduled_at,
)
