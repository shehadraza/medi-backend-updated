
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MedicationStatus = Literal[
    "active",
    "completed",
    "discontinued",
]


class MedicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(min_length=1, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)

    dose: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)

    food_instruction: str | None = Field(default=None, max_length=300)
    additional_instructions: str | None = Field(
        default=None,
        max_length=2000,
    )

    start_date: datetime | None = None
    end_date: datetime | None = None

    status: MedicationStatus = "active"

    @field_validator("medicine_name")
    @classmethod
    def validate_medicine_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Medicine name cannot be empty.")

        return value

    @field_validator(
        "generic_name",
        "brand_name",
        "strength",
        "dosage_form",
        "dose",
        "frequency",
        "duration",
        "food_instruction",
        "additional_instructions",
    )
    @classmethod
    def clean_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()
        return value or None

    @field_validator("end_date")
    @classmethod
    def validate_end_date(
        cls,
        value: datetime | None,
        info,
    ) -> datetime | None:
        start_date = info.data.get("start_date")

        if value is not None and start_date is not None:
            if value < start_date:
                raise ValueError(
                    "End date cannot be earlier than start date."
                )

        return value


class MedicationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_name: str | None = Field(default=None, min_length=1, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)

    dose: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)

    food_instruction: str | None = Field(default=None, max_length=300)
    additional_instructions: str | None = Field(
        default=None,
        max_length=2000,
    )

    start_date: datetime | None = None
    end_date: datetime | None = None

    status: MedicationStatus | None = None

    @field_validator("medicine_name")
    @classmethod
    def validate_medicine_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Medicine name cannot be empty.")

        return value


class MedicationResponse(BaseModel):
    id: str
    medicine_name: str
    generic_name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None

    dose: str | None = None
    frequency: str | None = None
    duration: str | None = None

    food_instruction: str | None = None
    additional_instructions: str | None = None

    status: MedicationStatus

    start_date: datetime | None = None
    end_date: datetime | None = None

    source: str
    prescription_id: str | None = None
    catalog_information: dict[str, Any] | None = None

    created_at: datetime
    updated_at: datetime


class MedicationListResponse(BaseModel):
    total: int
    medications: list[MedicationResponse]
