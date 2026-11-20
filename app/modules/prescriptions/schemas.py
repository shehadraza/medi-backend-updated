
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VerificationStatus = Literal[
    "needs_review",
    "verified",
    "uncertain",
]


class ExtractedMedicine(BaseModel):
    """
    Medicine information extracted from prescription OCR.
    Missing or unclear information must remain None.
    """

    model_config = ConfigDict(extra="forbid")

    medicine_name: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)

    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)

    dose: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)

    food_instruction: str | None = Field(default=None, max_length=200)
    additional_instructions: str | None = Field(
        default=None,
        max_length=1000,
    )

    # Exact OCR text supporting this medicine entry.
    source_text: str | None = Field(default=None, max_length=2000)

    verification_status: VerificationStatus = "needs_review"


class PrescriptionExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prescription_id: str

    extraction_status: Literal[
        "completed",
        "needs_review",
        "no_medicines_detected",
    ]

    medicines: list[ExtractedMedicine] = Field(
        default_factory=list,
        max_length=50,
    )

    warnings: list[str] = Field(
        default_factory=list,
        max_length=50,
    )

    requires_user_verification: bool = True


class MedicineCatalogEntry(BaseModel):
    """
    Verified catalog information.
    This information must come from a trusted catalog,
    not be invented by the extraction model.
    """

    model_config = ConfigDict(extra="forbid")

    generic_name: str
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None

    common_uses: list[str] = Field(default_factory=list)
    safety_information: list[str] = Field(default_factory=list)

    price_amount: float | None = Field(default=None, ge=0)
    currency: Literal["BDT"] = "BDT"
    pack_size: str | None = None

    source_name: str | None = None
    source_url: str | None = None
    last_updated: date | None = None

    is_verified: bool = False

from pydantic import BaseModel, ConfigDict, Field


class VerifyPrescriptionItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(min_length=1, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)
    dose: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)
    food_instruction: str | None = Field(default=None, max_length=200)
    additional_instructions: str | None = Field(default=None, max_length=2000)

class ConfirmPrescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool
