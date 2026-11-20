
import asyncio
import json
import os
import uuid

from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.encryption import (
    encrypt_bytes,
    decrypt_bytes,
    encrypt_data,
    decrypt_data,
)
from app.db.session import get_db
from app.models.medication import Prescription, PrescriptionItem
from app.models.user import User

from app.modules.medicines.prescription_sync import (
    sync_confirmed_prescription,
)

from app.modules.prescriptions.extraction_service import (
    extract_prescription_medicines,
)

from app.modules.prescriptions.ocr_service import (
    process_prescription_ocr,
    OCRServiceError,
)

from app.modules.prescriptions.schemas import (
    VerifyPrescriptionItemRequest,
    ConfirmPrescriptionRequest,
)


router = APIRouter(
    prefix="/prescriptions",
    tags=["Prescription Management"],
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

BACKEND_ROOT = Path(__file__).resolve().parents[3]
STORAGE_ROOT = (BACKEND_ROOT / "storage").resolve()
PRIVATE_STORAGE = STORAGE_ROOT / "prescriptions"

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def detect_file_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if (
        len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return "image/webp"

    if data.startswith(b"%PDF-"):
        return "application/pdf"

    return None


def get_file_path(prescription: Prescription) -> Path:
    relative_path = Path(prescription.file_path)

    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(
            status_code=500,
            detail="Invalid prescription storage reference.",
        )

    file_path = (STORAGE_ROOT / relative_path).resolve()

    try:
        file_path.relative_to(PRIVATE_STORAGE.resolve())
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail="Invalid prescription storage reference.",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Prescription file is unavailable.",
        )

    return file_path


async def get_user_prescription(
    prescription_id: str,
    user_id: str,
    db: AsyncSession,
) -> Prescription:
    result = await db.execute(
        select(Prescription).where(
            Prescription.id == prescription_id,
            Prescription.user_id == user_id,
        )
    )

    prescription = result.scalar_one_or_none()

    if prescription is None:
        raise HTTPException(
            status_code=404,
            detail="Prescription not found.",
        )

    return prescription


def ocr_associated_data(
    user_id: str,
    prescription_id: str,
) -> bytes:
    return (
        f"medi:prescription-ocr:v1:{user_id}:{prescription_id}"
    ).encode("utf-8")


def prescription_item_associated_data(
    user_id: str,
    prescription_id: str,
    item_id: str,
) -> bytes:
    return (
        f"medi:prescription-item:v1:{user_id}:{prescription_id}:{item_id}"
    ).encode("utf-8")


def build_ocr_response(
    prescription: Prescription,
    user_id: str,
) -> dict:
    if not prescription.encrypted_ocr_data:
        raise HTTPException(
            status_code=404,
            detail="OCR result is not available yet.",
        )

    try:
        decrypted = decrypt_data(
            prescription.encrypted_ocr_data,
            associated_data=ocr_associated_data(
                user_id,
                prescription.id,
            ),
        )

        payload = json.loads(decrypted)

    except (InvalidTag, ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="OCR data integrity verification failed.",
        )

    return {
        "prescription_id": prescription.id,
        "status": prescription.status,
        "ocr": payload,
        "requires_user_verification": True,
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_prescription(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prescription_id = str(uuid.uuid4())
    saved_path: Path | None = None

    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)

        if not data:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty.",
            )

        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="File size must not exceed 10 MB.",
            )

        actual_type = detect_file_type(data)

        if actual_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG, WebP and PDF files are allowed.",
            )

        user_id = str(current_user.id)

        user_directory = PRIVATE_STORAGE / user_id
        user_directory.mkdir(parents=True, exist_ok=True)

        filename = f"{prescription_id}.medi"
        saved_path = user_directory / filename

        associated_data = (
            f"medi:prescription-file:v1:{user_id}:{prescription_id}"
        ).encode("utf-8")

        encrypted_file = encrypt_bytes(
            data,
            associated_data=associated_data,
        )

        with saved_path.open("xb") as destination:
            destination.write(encrypted_file)
            destination.flush()
            os.fsync(destination.fileno())

        relative_path = (
            Path("prescriptions") / user_id / filename
        ).as_posix()

        prescription = Prescription(
            id=prescription_id,
            user_id=user_id,
            file_path=relative_path,
            file_type=actual_type,
            status="uploaded",
            encryption_version=1,
        )

        db.add(prescription)
        await db.commit()
        await db.refresh(prescription)

        return {
            "message": "Prescription uploaded securely.",
            "prescription": {
                "id": prescription.id,
                "file_type": prescription.file_type,
                "status": prescription.status,
                "created_at": prescription.created_at,
            },
        }

    except HTTPException:
        await db.rollback()

        if saved_path and saved_path.exists():
            saved_path.unlink(missing_ok=True)

        raise

    except Exception:
        await db.rollback()

        if saved_path and saved_path.exists():
            saved_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail="Prescription upload failed. Please try again.",
        )

    finally:
        await file.close()


@router.get("")
async def list_prescriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Prescription)
        .where(Prescription.user_id == str(current_user.id))
        .order_by(Prescription.created_at.desc())
    )

    prescriptions = result.scalars().all()

    return {
        "total": len(prescriptions),
        "prescriptions": [
            {
                "id": item.id,
                "file_type": item.file_type,
                "status": item.status,
                "created_at": item.created_at,
                "verified_at": item.verified_at,
                "confirmed_at": item.confirmed_at,
            }
            for item in prescriptions
        ],
    }


@router.get("/{prescription_id}/file")
async def download_prescription(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    file_path = get_file_path(prescription)

    associated_data = (
        f"medi:prescription-file:v1:{user_id}:{prescription.id}"
    ).encode("utf-8")

    try:
        encrypted_file = await asyncio.to_thread(
            file_path.read_bytes
        )

        decrypted_file = decrypt_bytes(
            encrypted_file,
            associated_data=associated_data,
        )

    except (InvalidTag, ValueError):
        raise HTTPException(
            status_code=500,
            detail="Prescription integrity verification failed.",
        )

    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Unable to read prescription file.",
        )

    extension = ALLOWED_TYPES.get(
        prescription.file_type,
        ".bin",
    )

    return Response(
        content=decrypted_file,
        media_type=prescription.file_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="prescription{extension}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{prescription_id}/process")
async def process_prescription(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    if (
        prescription.encrypted_ocr_data
        and prescription.status in ("needs_review", "ocr_completed")
    ):
        return JSONResponse(
            content=build_ocr_response(prescription, user_id),
            headers={"Cache-Control": "private, no-store"},
        )

    if prescription.status not in ("uploaded", "ocr_failed"):
        raise HTTPException(
            status_code=409,
            detail="Prescription cannot be processed in its current state.",
        )

    file_path = get_file_path(prescription)

    file_associated_data = (
        f"medi:prescription-file:v1:{user_id}:{prescription.id}"
    ).encode("utf-8")

    try:
        encrypted_file = await asyncio.to_thread(
            file_path.read_bytes
        )

        decrypted_file = decrypt_bytes(
            encrypted_file,
            associated_data=file_associated_data,
        )

    except (InvalidTag, ValueError):
        raise HTTPException(
            status_code=500,
            detail="Prescription integrity verification failed.",
        )

    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Unable to read prescription file.",
        )

    prescription.status = "processing"
    await db.commit()

    try:
        ocr_result = await asyncio.to_thread(
            process_prescription_ocr,
            decrypted_file,
            prescription.file_type,
        )

        full_text = ocr_result.get("full_text", "").strip()

        if not full_text:
            raise OCRServiceError(
                "No readable text was detected in the prescription."
            )

        safe_result = {
            "engine": ocr_result.get("engine"),
            "version": ocr_result.get("engine_version"),
            "languages": ocr_result.get("languages"),
            "page_count": ocr_result.get("page_count"),
            "pages": ocr_result.get("pages", []),
            "full_text": full_text,
            "average_confidence": ocr_result.get(
                "average_confidence"
            ),
            "requires_user_verification": True,
        }

        encrypted_ocr = encrypt_data(
            json.dumps(
                safe_result,
                ensure_ascii=False,
            ),
            associated_data=ocr_associated_data(
                user_id,
                prescription.id,
            ),
        )

        prescription.encrypted_ocr_data = encrypted_ocr
        prescription.status = "needs_review"

        await db.commit()
        await db.refresh(prescription)

        return JSONResponse(
            content=build_ocr_response(prescription, user_id),
            headers={"Cache-Control": "private, no-store"},
        )

    except Exception:
        await db.rollback()

        failed_prescription = await get_user_prescription(
            prescription_id,
            user_id,
            db,
        )

        failed_prescription.status = "ocr_failed"
        await db.commit()

        raise HTTPException(
            status_code=422,
            detail=(
                "Prescription OCR could not be completed. "
                "Please check the file and try again."
            ),
        )


@router.get("/{prescription_id}/ocr")
async def get_prescription_ocr(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    result = build_ocr_response(
        prescription,
        user_id,
    )

    return JSONResponse(
        content=result,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{prescription_id}/extract")
async def extract_prescription(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    if prescription.confirmed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="A confirmed prescription cannot be extracted again.",
        )

    if not prescription.encrypted_ocr_data:
        raise HTTPException(
            status_code=409,
            detail="Process the prescription OCR before extraction.",
        )

    existing_result = await db.execute(
        select(PrescriptionItem).where(
            PrescriptionItem.prescription_id == prescription_id
        )
    )

    existing_items = existing_result.scalars().all()

    if existing_items:
        raise HTTPException(
            status_code=409,
            detail="Medicine extraction already exists for this prescription.",
        )

    ocr_response = build_ocr_response(
        prescription,
        user_id,
    )

    ocr_payload = ocr_response["ocr"]

    try:
        extraction = extract_prescription_medicines(
            prescription_id,
            ocr_payload,
        )

    except Exception:
        raise HTTPException(
            status_code=422,
            detail="Medicine extraction failed. Please review the OCR text.",
        )

    created_items = []

    try:
        for medicine in extraction.medicines:
            item_id = str(uuid.uuid4())
            medicine_data = medicine.model_dump()

            encrypted_medicine = encrypt_data(
                json.dumps(
                    medicine_data,
                    ensure_ascii=False,
                ),
                associated_data=prescription_item_associated_data(
                    user_id,
                    prescription_id,
                    item_id,
                ),
            )

            item = PrescriptionItem(
                id=item_id,
                prescription_id=prescription_id,
                encrypted_data=encrypted_medicine,
                verification_status=medicine.verification_status,
            )

            db.add(item)

            created_items.append({
                "id": item_id,
                **medicine_data,
            })

        prescription.status = "needs_review"

        await db.commit()

    except Exception:
        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to save extracted medicine information.",
        )

    return JSONResponse(
        content={
            "prescription_id": prescription_id,
            "extraction_status": extraction.extraction_status,
            "medicines": created_items,
            "warnings": extraction.warnings,
            "requires_user_verification": True,
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{prescription_id}/extracted")
async def get_extracted_prescription(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    result = await db.execute(
        select(PrescriptionItem).where(
            PrescriptionItem.prescription_id == prescription_id
        )
    )

    items = result.scalars().all()
    medicines = []

    try:
        for item in items:
            decrypted = decrypt_data(
                item.encrypted_data,
                associated_data=prescription_item_associated_data(
                    user_id,
                    prescription_id,
                    item.id,
                ),
            )

            medicine_data = json.loads(decrypted)

            medicines.append({
                "id": item.id,
                **medicine_data,
                "verification_status": item.verification_status,
            })

    except (InvalidTag, ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Extracted medicine data integrity verification failed.",
        )

    return JSONResponse(
        content={
            "prescription_id": prescription_id,
            "total": len(medicines),
            "medicines": medicines,
            "requires_user_verification": True,
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.put("/{prescription_id}/items/{item_id}/verify")
async def verify_prescription_item(
    prescription_id: str,
    item_id: str,
    payload: VerifyPrescriptionItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    if prescription.confirmed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="A confirmed prescription cannot be modified.",
        )

    result = await db.execute(
        select(PrescriptionItem).where(
            PrescriptionItem.id == item_id,
            PrescriptionItem.prescription_id == prescription.id,
        )
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Prescription medicine item not found.",
        )

    medicine_data = payload.model_dump()

    try:
        encrypted_medicine = encrypt_data(
            json.dumps(
                medicine_data,
                ensure_ascii=False,
            ),
            associated_data=prescription_item_associated_data(
                user_id,
                prescription_id,
                item_id,
            ),
        )

        item.encrypted_data = encrypted_medicine
        item.verification_status = "verified"

        await db.commit()
        await db.refresh(item)

    except Exception:
        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to save medicine verification.",
        )

    return JSONResponse(
        content={
            "message": "Medicine information verified by the user.",
            "prescription_id": prescription_id,
            "item_id": item_id,
            "verification_status": item.verification_status,
            "medicine": medicine_data,
            "prescription_confirmed": False,
            "requires_final_user_confirmation": True,
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{prescription_id}/confirm")
async def confirm_prescription(
    prescription_id: str,
    payload: ConfirmPrescriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = str(current_user.id)

    prescription = await get_user_prescription(
        prescription_id,
        user_id,
        db,
    )

    if not payload.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Explicit user confirmation is required.",
        )

    if prescription.confirmed_at is not None:
        raise HTTPException(
            status_code=409,
            detail="This prescription has already been confirmed.",
        )

    result = await db.execute(
        select(PrescriptionItem).where(
            PrescriptionItem.prescription_id == prescription.id
        )
    )

    items = result.scalars().all()

    if not items:
        raise HTTPException(
            status_code=409,
            detail="No extracted medicines are available.",
        )

    unverified_items = [
        item.id
        for item in items
        if item.verification_status != "verified"
    ]

    if unverified_items:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "All medicines must be verified first.",
                "unverified_item_ids": unverified_items,
            },
        )

    now = datetime.now(timezone.utc)

    prescription.verified_at = now
    prescription.confirmed_at = now
    prescription.status = "confirmed"

    try:
        cabinet_result = await sync_confirmed_prescription(
            db=db,
            prescription_id=prescription.id,
            user_id=user_id,
        )

        await db.commit()
        await db.refresh(prescription)

    except ValueError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    except Exception:
        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "Prescription confirmation and Cabinet "
                "synchronization failed."
            ),
        )

    return JSONResponse(
        content={
            "message": "Prescription confirmed successfully.",
            "prescription_id": prescription.id,
            "status": prescription.status,
            "verified_at": (
                prescription.verified_at.isoformat()
                if prescription.verified_at else None
            ),
            "confirmed_at": (
                prescription.confirmed_at.isoformat()
                if prescription.confirmed_at else None
            ),
            "medicine_count": len(items),
            "cabinet_sync_status": "completed",
            "cabinet_created_count": cabinet_result["created_count"],
            "cabinet_existing_count": cabinet_result["existing_count"],
            "reminder_sync_status": "not_configured",
        },
        headers={"Cache-Control": "private, no-store"},
    )
