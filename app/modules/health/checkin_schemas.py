"""Validated API schemas for user-reported daily health check-ins."""

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _CheckInFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sleep_duration_hours: float | None = Field(default=None, ge=0, le=24, allow_inf_nan=False)
    sleep_quality: Literal["poor", "fair", "good", "excellent"] | None = None
    water_intake_liters: float | None = Field(default=None, ge=0, le=20, allow_inf_nan=False)
    physical_activity: str | None = Field(default=None, max_length=100)
    physical_activity_minutes: int | None = Field(default=None, ge=0, le=1440)
    screen_time_hours: float | None = Field(default=None, ge=0, le=24, allow_inf_nan=False)
    eating_habits: str | None = Field(default=None, max_length=500)
    junk_food_portions: int | None = Field(default=None, ge=0, le=20)
    wellbeing_level: int | None = Field(default=None, ge=1, le=5)
    energy_level: int | None = Field(default=None, ge=1, le=5)
    symptoms: list[str] | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("physical_activity", "eating_habits", "notes")
    @classmethod
    def reject_blank_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Text fields cannot be blank.")
        return value

    @field_validator("symptoms")
    @classmethod
    def validate_symptoms(cls, value):
        if value is not None:
            if any(not item.strip() or len(item) > 200 for item in value):
                raise ValueError("Each symptom must contain 1 to 200 characters.")
        return value


class CheckInCreateRequest(_CheckInFields):
    local_date: date
    timezone_name: str = Field(min_length=1, max_length=100)

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError("A valid IANA timezone is required.") from exc
        return value

    @model_validator(mode="after")
    def require_some_data(self):
        data_fields = set(type(self).model_fields) - {"local_date", "timezone_name"}
        if not any(getattr(self, field) is not None for field in data_fields):
            raise ValueError("At least one health check-in field is required.")
        return self


class CheckInPatchRequest(_CheckInFields):
    @model_validator(mode="after")
    def require_patch_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied.")
        return self


class CheckInResponse(BaseModel):
    id: str
    local_date: date
    timezone_name: str
    data: dict
    created_at: datetime
    updated_at: datetime


class CheckInListResponse(BaseModel):
    items: list[CheckInResponse]
    limit: int
    offset: int
