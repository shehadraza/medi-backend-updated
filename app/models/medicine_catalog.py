
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MedicineCatalog(Base):
    """
    Public, verified medicine information.

    Patient-specific dosage and treatment information must remain
    in the encrypted Medication model, not in this catalog.
    """

    __tablename__ = "medicine_catalog"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    verified_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ) 

    # Medicine identity
    generic_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    brand_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    manufacturer: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    strength: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    dosage_form: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    route: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Public medical information.
    # These fields require trusted references and admin review.
    common_uses: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    safety_information: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Verified market pricing.
    price_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="BDT",
        nullable=False,
    )
    pack_size: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # Source and verification details.
    source_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    source_reference: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Only verified and published entries appear in the user catalog.
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


Index(
    "ix_medicine_catalog_generic_brand",
    MedicineCatalog.generic_name,
    MedicineCatalog.brand_name,
)

Index(
    "ix_medicine_catalog_published_verified",
    MedicineCatalog.is_published,
    MedicineCatalog.is_verified,
)
