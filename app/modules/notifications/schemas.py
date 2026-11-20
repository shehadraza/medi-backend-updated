
from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationItem(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    created_at: datetime
    sent_at: datetime | None = None
    read_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationReadResponse(BaseModel):
    success: bool
    notification_id: str


class NotificationReadAllResponse(BaseModel):
    success: bool
    updated_count: int


class HealthReminderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=500)
    scheduled_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    reminder_kind: Literal["health", "prescription_followup"] = "health"
    prescription_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator("scheduled_at")
    @classmethod
    def validate_schedule(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value <= datetime.now(timezone.utc) or value > datetime.now(timezone.utc) + timedelta(days=365):
            raise ValueError("scheduled_at must include timezone and be within the next year")
        return value

    @field_validator("prescription_id")
    @classmethod
    def validate_prescription_id(cls, value: str | None) -> str | None:
        if value is not None:
            from uuid import UUID
            try:
                return str(UUID(value))
            except ValueError as exc:
                raise ValueError("prescription_id must be a UUID") from exc
        return value


class HealthReminderResponse(BaseModel):
    notification_id: str
    channel: str = "in_app"
    scheduled_at: datetime
