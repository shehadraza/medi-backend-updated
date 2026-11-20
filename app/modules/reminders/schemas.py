
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DoseStatus = Literal["pending", "taken", "skipped", "missed"]


class MedicationScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_id: str = Field(min_length=36, max_length=36)

    reminder_times: list[time] = Field(
        min_length=1,
        max_length=12,
    )

    recurrence: Literal["daily", "weekly"] = "daily"

    weekdays: list[int] = Field(default_factory=list)

    timezone_name: str = "Asia/Dhaka"

    start_date: date | None = None
    end_date: date | None = None

    reminder_enabled: bool = True

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone name.")

        return value

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate weekdays are not allowed.")

        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Weekdays must be between 0 and 6.")

        return value

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.reminder_times:
            raise ValueError("At least one reminder time is required.")

        if len(set(self.reminder_times)) != len(self.reminder_times):
            raise ValueError("Duplicate reminder times are not allowed.")

        if self.recurrence == "weekly" and not self.weekdays:
            raise ValueError(
                "Select at least one weekday for a weekly schedule."
            )

        if self.recurrence == "daily" and self.weekdays:
            raise ValueError(
                "Weekdays should only be provided for weekly schedules."
            )

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("End date cannot be before start date.")

        return self


class MedicationScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder_times: list[time] | None = Field(
        default=None,
        min_length=1,
        max_length=12,
    )

    recurrence: Literal["daily", "weekly"] | None = None
    weekdays: list[int] | None = None
    timezone_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    reminder_enabled: bool | None = None

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone name.")

        return value

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(
        cls,
        value: list[int] | None,
    ) -> list[int] | None:
        if value is None:
            return None

        if len(value) != len(set(value)):
            raise ValueError("Duplicate weekdays are not allowed.")

        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Weekdays must be between 0 and 6.")

        return value


class MedicationScheduleResponse(BaseModel):
    id: str
    medication_id: str
    reminder_times: list[str]
    recurrence: Literal["daily", "weekly"]
    weekdays: list[int]
    timezone_name: str
    start_date: date | None = None
    end_date: date | None = None
    reminder_enabled: bool
    next_dose_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DoseActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["taken", "skipped"]


class MedicationLogResponse(BaseModel):
    id: str
    medication_id: str
    schedule_id: str | None = None
    scheduled_at: datetime
    taken_at: datetime | None = None
    status: DoseStatus
    created_at: datetime


class MedicationAdherenceResponse(BaseModel):
    total_doses: int
    taken: int
    skipped: int
    missed: int
    pending: int
    adherence_percentage: float

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DoseActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["taken", "skipped"]


class MedicationLogResponse(BaseModel):
    id: str
    medication_id: str
    schedule_id: str | None = None
    scheduled_at: datetime
    taken_at: datetime | None = None
    status: Literal["pending", "taken", "skipped", "missed"]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationAdherenceResponse(BaseModel):
    total_doses: int = Field(ge=0)
    taken: int = Field(ge=0)
    skipped: int = Field(ge=0)
    missed: int = Field(ge=0)
    pending: int = Field(ge=0)
    adherence_percentage: float = Field(ge=0, le=100)
