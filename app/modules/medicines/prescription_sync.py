
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_data, decrypt_data
from app.models.medication import (
    Medication,
    Prescription,
    PrescriptionItem,
)
from app.models.medicine_catalog import MedicineCatalog


def item_associated_data(
    user_id: str,
    prescription_id: str,
    item_id: str,
) -> bytes:
    return (
        f"medi:prescription-item:v1:{user_id}:{prescription_id}:{item_id}"
    ).encode("utf-8")


def medication_associated_data(
    user_id: str,
    medication_id: str,
) -> bytes:
    return (
        f"medi:medication:v1:{user_id}:{medication_id}"
    ).encode("utf-8")


def normalize(value: object | None) -> str:
    """Normalize medicine identity fields for conservative matching."""
    if value is None:
        return ""

    return re.sub(r"\s+", "", str(value).strip().casefold())


def match_catalog_information(
    medicine_data: dict,
    catalog_records: list[MedicineCatalog],
) -> dict:
    """
    Match only verified and published catalog records.
    Never guess when medicine identity is incomplete or ambiguous.
    """

    possible_names = {
        normalize(medicine_data.get("medicine_name")),
        normalize(medicine_data.get("generic_name")),
        normalize(medicine_data.get("brand_name")),
    }
    possible_names.discard("")

    extracted_strength = normalize(medicine_data.get("strength"))
    extracted_form = normalize(medicine_data.get("dosage_form"))

    if not possible_names or not extracted_strength:
        return {
            "status": "insufficient_identity",
            "message": "Medicine name or strength needs confirmation.",
        }

    matches = []

    for record in catalog_records:
        catalog_names = {
            normalize(record.generic_name),
            normalize(record.brand_name),
        }
        catalog_names.discard("")

        if not possible_names.intersection(catalog_names):
            continue

        if normalize(record.strength) != extracted_strength:
            continue

        if extracted_form and normalize(record.dosage_form) != extracted_form:
            continue

        matches.append(record)

    if not matches:
        return {
            "status": "not_found",
            "message": "No verified catalog match was found.",
        }

    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "message": "Multiple catalog matches need review.",
        }

    record = matches[0]

    return {
        "status": "matched",
        "medicine_catalog_id": record.id,
        "generic_name": record.generic_name,
        "brand_name": record.brand_name,
        "manufacturer": record.manufacturer,
        "strength": record.strength,
        "dosage_form": record.dosage_form,
        "route": record.route,
        "common_uses": record.common_uses or [],
        "safety_information": record.safety_information or [],
        "price": {
            "amount": (
                str(record.price_amount)
                if record.price_amount is not None
                else None
            ),
            "currency": record.currency,
            "pack_size": record.pack_size,
            "source_name": record.source_name,
            "source_url": record.source_url,
            "source_reference": record.source_reference,
            "catalog_verified_at": (
                record.last_verified_at.isoformat()
                if record.last_verified_at
                else None
            ),
        },
        "catalog_verified": True,
        "catalog_published": True,
    }


async def sync_confirmed_prescription(
    db: AsyncSession,
    prescription_id: str,
    user_id: str,
) -> dict:
    """
    Create encrypted Medicine Cabinet entries from a confirmed
    prescription and attach matching verified catalog information.

    Prescription-specific dosage remains separate from general
    catalog information. Schedules are not created automatically.
    """

    prescription_result = await db.execute(
        select(Prescription)
        .where(
            Prescription.id == prescription_id,
            Prescription.user_id == user_id,
        )
        .with_for_update()
    )

    prescription = prescription_result.scalar_one_or_none()

    if prescription is None:
        raise ValueError("Prescription not found.")

    if prescription.confirmed_at is None:
        raise ValueError("Prescription has not been confirmed.")

    items_result = await db.execute(
        select(PrescriptionItem)
        .where(
            PrescriptionItem.prescription_id == prescription_id
        )
        .order_by(PrescriptionItem.created_at.asc())
    )

    items = items_result.scalars().all()

    if not items:
        raise ValueError("No prescription items were found.")

    if any(item.verification_status != "verified" for item in items):
        raise ValueError("All prescription items must be verified.")

    catalog_result = await db.execute(
        select(MedicineCatalog).where(
            MedicineCatalog.is_verified.is_(True),
            MedicineCatalog.is_published.is_(True),
        )
    )
    catalog_records = catalog_result.scalars().all()

    created_count = 0
    existing_count = 0
    matched_count = 0
    unmatched_count = 0
    cabinet_medications = []

    for item in items:
        existing_result = await db.execute(
            select(Medication).where(
                Medication.prescription_item_id == item.id
            )
        )

        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            if existing.user_id != user_id:
                raise ValueError(
                    "Medication ownership verification failed."
                )

            existing_count += 1
            cabinet_medications.append(existing.id)
            continue

        medicine_json = decrypt_data(
            item.encrypted_data,
            associated_data=item_associated_data(
                user_id,
                prescription_id,
                item.id,
            ),
        )

        medicine_data = json.loads(medicine_json)

        catalog_information = match_catalog_information(
            medicine_data,
            catalog_records,
        )

        if catalog_information["status"] == "matched":
            matched_count += 1
        else:
            unmatched_count += 1

        medication_id = str(uuid.uuid4())

        cabinet_data = {
            **medicine_data,
            "source": "confirmed_prescription",
            "prescription_id": prescription_id,
            "prescription_item_id": item.id,
            "user_verified": True,
            "clinician_authenticity_verified": False,
            "catalog_information": catalog_information,
            "schedule_status": "not_configured",
        }

        encrypted_medication = encrypt_data(
            json.dumps(
                cabinet_data,
                ensure_ascii=False,
            ),
            associated_data=medication_associated_data(
                user_id,
                medication_id,
            ),
        )

        medication = Medication(
            id=medication_id,
            user_id=user_id,
            prescription_id=prescription_id,
            prescription_item_id=item.id,
            encrypted_data=encrypted_medication,
            encryption_version=1,
            status="active",
        )

        db.add(medication)

        created_count += 1
        cabinet_medications.append(medication_id)

    await db.flush()

    return {
        "prescription_id": prescription_id,
        "created_count": created_count,
        "existing_count": existing_count,
        "catalog_matched_count": matched_count,
        "catalog_unmatched_count": unmatched_count,
        "medication_ids": cabinet_medications,
        "schedule_status": "not_configured",
    }
