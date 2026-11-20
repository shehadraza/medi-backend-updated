
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data, encrypt_data
from app.db.session import get_db
from app.models.medication import Medication
from app.core.dependencies import get_current_user
from app.modules.medicines.schemas import (
    MedicationCreateRequest,
    MedicationListResponse,
    MedicationResponse,
    MedicationUpdateRequest,
)


router = APIRouter(
    prefix="/medicines",
    tags=["Medicine Cabinet"],
)


def medication_aad(user_id: str, medication_id: str) -> bytes:
    return (
        f"medi:medication:v1:{user_id}:{medication_id}"
    ).encode("utf-8")


def encrypt_medication(
    user_id: str,
    medication_id: str,
    data: dict,
) -> str:
    return encrypt_data(
        json.dumps(data, ensure_ascii=False),
        associated_data=medication_aad(user_id, medication_id),
    )


def decrypt_medication(medication: Medication) -> dict:
    try:
        plaintext = decrypt_data(
            medication.encrypted_data,
            associated_data=medication_aad(
                medication.user_id,
                medication.id,
            ),
        )
        return json.loads(plaintext)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to securely read this medication record.",
        ) from exc


def serialize_medication(
    medication: Medication,
) -> MedicationResponse:
    data = decrypt_medication(medication)

    return MedicationResponse(
        id=medication.id,
        medicine_name=data["medicine_name"],
        generic_name=data.get("generic_name"),
        brand_name=data.get("brand_name"),
        strength=data.get("strength"),
        dosage_form=data.get("dosage_form"),
        dose=data.get("dose"),
        frequency=data.get("frequency"),
        duration=data.get("duration"),
        food_instruction=data.get("food_instruction"),
        additional_instructions=data.get("additional_instructions"),
        status=medication.status,
        start_date=medication.start_date,
        end_date=medication.end_date,
        source=data.get("source", "manual"),
        prescription_id=medication.prescription_id,
        catalog_information=data.get("catalog_information"),
        created_at=medication.created_at,
        updated_at=medication.updated_at,
    )


async def get_owned_medication(
    db: AsyncSession,
    user_id: str,
    medication_id: str,
) -> Medication:
    result = await db.execute(
        select(Medication).where(
            Medication.id == medication_id,
            Medication.user_id == user_id,
        )
    )

    medication = result.scalar_one_or_none()

    if medication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medication not found.",
        )

    return medication


@router.get(
    "",
    response_model=MedicationListResponse,
)
async def list_medications(
    search: str | None = Query(default=None, max_length=200),
    medication_status: str | None = Query(
        default=None,
        alias="status",
        pattern="^(active|completed|discontinued)$",
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    statement = select(Medication).where(
        Medication.user_id == current_user.id,
        Medication.status != "deleted",
    )

    if medication_status:
        statement = statement.where(
            Medication.status == medication_status
        )

    result = await db.execute(
        statement.order_by(Medication.created_at.desc())
    )

    records = result.scalars().all()

    medications = [
        serialize_medication(record)
        for record in records
    ]

    if search:
        search_term = search.casefold().strip()

        medications = [
            item
            for item in medications
            if search_term in item.medicine_name.casefold()
            or search_term in (item.generic_name or "").casefold()
            or search_term in (item.brand_name or "").casefold()
        ]

    return MedicationListResponse(
        total=len(medications),
        medications=medications,
    )


@router.post(
    "",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_medication(
    payload: MedicationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if (
        payload.start_date is not None
        and payload.end_date is not None
        and payload.end_date < payload.start_date
    ):
        raise HTTPException(
            status_code=422,
            detail="End date cannot be earlier than start date.",
        )

    medication_id = str(uuid.uuid4())

    data = payload.model_dump(
        exclude={"start_date", "end_date", "status"},
    )
    data["source"] = "manual"
    data["user_verified"] = True
    data["clinician_authenticity_verified"] = False
    data["schedule_status"] = "not_configured"

    medication = Medication(
        id=medication_id,
        user_id=current_user.id,
        encrypted_data=encrypt_medication(
            current_user.id,
            medication_id,
            data,
        ),
        encryption_version=1,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )

    db.add(medication)
    await db.commit()
    await db.refresh(medication)

    return serialize_medication(medication)


@router.get(
    "/{medication_id}",
    response_model=MedicationResponse,
)
async def get_medication(
    medication_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    medication = await get_owned_medication(
        db,
        current_user.id,
        medication_id,
    )

    if medication.status == "deleted":
        raise HTTPException(status_code=404, detail="Medication not found.")

    return serialize_medication(medication)


@router.patch(
    "/{medication_id}",
    response_model=MedicationResponse,
)
async def update_medication(
    medication_id: str,
    payload: MedicationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    medication = await get_owned_medication(
        db,
        current_user.id,
        medication_id,
    )

    if medication.status == "deleted":
        raise HTTPException(status_code=404, detail="Medication not found.")

    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="At least one field must be provided.",
        )

    data = decrypt_medication(medication)

    date_fields = {"start_date", "end_date"}
    status_value = changes.pop("status", None)

    for field in date_fields:
        if field in changes:
            setattr(medication, field, changes.pop(field))

    for field, value in changes.items():
        data[field] = value

    if (
        medication.start_date is not None
        and medication.end_date is not None
        and medication.end_date < medication.start_date
    ):
        raise HTTPException(
            status_code=422,
            detail="End date cannot be earlier than start date.",
        )

    if status_value is not None:
        medication.status = status_value

    medication.encrypted_data = encrypt_medication(
        current_user.id,
        medication.id,
        data,
    )
    medication.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(medication)

    return serialize_medication(medication)


@router.delete(
    "/{medication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_medication(
    medication_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    medication = await get_owned_medication(
        db,
        current_user.id,
        medication_id,
    )

    if medication.status == "deleted":
        raise HTTPException(status_code=404, detail="Medication not found.")

    # Soft delete: preserve historical prescription and adherence references.
    medication.status = "deleted"
    medication.updated_at = datetime.now(timezone.utc)

    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
