
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)


Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class CatalogBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generic_name: Name
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)

    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)
    route: str | None = Field(default=None, max_length=100)

    common_uses: list[str] | None = Field(default=None, max_length=30)
    safety_information: list[str] | None = Field(default=None, max_length=30)

    price_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="BDT", min_length=3, max_length=3)
    pack_size: str | None = Field(default=None, max_length=150)

    source_name: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    source_reference: str | None = None


class CatalogCreateRequest(CatalogBase):
    pass


class CatalogUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generic_name: str | None = Field(default=None, min_length=1, max_length=255)
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)

    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)
    route: str | None = Field(default=None, max_length=100)

    common_uses: list[str] | None = Field(default=None, max_length=30)
    safety_information: list[str] | None = Field(default=None, max_length=30)

    price_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    pack_size: str | None = Field(default=None, max_length=150)

    source_name: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    source_reference: str | None = None


class CatalogVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=2, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    source_reference: str | None = None
    last_verified_at: datetime


class CatalogPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(
        description="Explicit confirmation that this verified entry is ready for publication."
    )


class CatalogAdminResponse(CatalogBase):
    model_config = ConfigDict(from_attributes=True)

    id: str

    is_verified: bool
    is_published: bool

    created_by: str | None
    updated_by: str | None
    verified_by: str | None

    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CatalogPublicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    generic_name: str
    brand_name: str | None
    manufacturer: str | None

    strength: str | None
    dosage_form: str | None
    route: str | None

    common_uses: list[str] | None
    safety_information: list[str] | None

    price_amount: Decimal | None
    currency: str
    pack_size: str | None

    source_name: str | None
    source_url: str | None
    last_verified_at: datetime


class CatalogListResponse(BaseModel):
    total: int
    items: list[CatalogPublicResponse]
