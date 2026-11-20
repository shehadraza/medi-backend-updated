
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from types import SimpleNamespace

from app.modules.prescriptions.schemas import ExtractedMedicine
from app.main import app
from app.db.session import engine, get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.medication import Prescription, PrescriptionItem
from app.modules.prescriptions import routes as prescription_routes


@pytest_asyncio.fixture(loop_scope="session")
async def prescription_api_client():
    user_id = str(uuid.uuid4())

    async with engine.connect() as connection:
        transaction = await connection.begin()

        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as db:
                user = User(
                    id=user_id,
                    full_name="Prescription Test",
                    email=f"prescription-{user_id}@example.com",
                    password_hash="test-only-password",
                    is_active=True,
                    is_verified=True,
                )

                db.add(user)
                await db.flush()

                async def override_get_db():
                    yield db

                async def override_get_current_user():
                    return user

                app.dependency_overrides[get_db] = override_get_db
                app.dependency_overrides[get_current_user] = (
                    override_get_current_user
                )

                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    yield client, user, db

        finally:
            app.dependency_overrides.clear()

            if transaction.is_active:
                await transaction.rollback()



def confirmation_url(prescription_id):
    return f"/prescriptions/{prescription_id}/confirm"

    for route in app.routes:
        path = getattr(route, "path", "")
        if (
            path.endswith("/{prescription_id}/confirm")
            and "POST" in getattr(route, "methods", set())
        ):
            return path.replace(
                "{prescription_id}",
                prescription_id,
            )

    raise AssertionError("Prescription confirmation route not found")


async def create_prescription(db, user, verified=True, confirmed=False):
    prescription_id = str(uuid.uuid4())

    prescription = Prescription(
        id=prescription_id,
        user_id=user.id,
        file_path="test-prescription.jpg",
        file_type="image/jpeg",
        status="confirmed" if confirmed else "uploaded",
        confirmed_at=(
            datetime.now(timezone.utc) if confirmed else None
        ),
    )

    item = PrescriptionItem(
        id=str(uuid.uuid4()),
        prescription_id=prescription_id,
        encrypted_data="test-encrypted-placeholder",
        verification_status=(
            "verified" if verified else "needs_review"
        ),
    )

    db.add_all([prescription, item])
    await db.flush()

    return prescription


@pytest.mark.asyncio(loop_scope="session")
async def test_confirmation_rejects_unverified_medicines(
    prescription_api_client,
):
    client, user, db = prescription_api_client

    prescription = await create_prescription(
        db, user, verified=False
    )

    response = await client.post(
        confirmation_url(prescription.id),
        json={"confirmed": True},
    )

    assert response.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_confirmation_requires_explicit_user_approval(
    prescription_api_client,
):
    client, user, db = prescription_api_client

    prescription = await create_prescription(db, user)

    response = await client.post(
        confirmation_url(prescription.id),
        json={"confirmed": False},
    )

    assert response.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_already_confirmed_prescription_cannot_be_confirmed_again(
    prescription_api_client,
):
    client, user, db = prescription_api_client

    prescription = await create_prescription(
        db, user, confirmed=True
    )

    response = await client.post(
        confirmation_url(prescription.id),
        json={"confirmed": True},
    )

    assert response.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_verified_prescription_triggers_cabinet_sync(
    prescription_api_client,
    monkeypatch,
):
    client, user, db = prescription_api_client

    prescription = await create_prescription(db, user)

    sync_calls = []

    async def mock_sync(**kwargs):
        sync_calls.append(kwargs)

        return {
            "created_count": 1,
            "existing_count": 0,
            "catalog_matched_count": 0,
            "catalog_unmatched_count": 1,
        }

    monkeypatch.setattr(
        prescription_routes,
        "sync_confirmed_prescription",
        mock_sync,
    )

    response = await client.post(
        confirmation_url(prescription.id),
        json={"confirmed": True},
    )

    assert response.status_code == 200
    assert len(sync_calls) == 1
    assert sync_calls[0]["prescription_id"] == prescription.id
    assert sync_calls[0]["user_id"] == user.id

    data = response.json()
    print("CONFIRM_RESPONSE:", data)

    assert data["cabinet_sync_status"] == "completed"
    assert data["cabinet_created_count"] == 1

@pytest.mark.asyncio(loop_scope="session")
async def test_prescription_upload_to_cabinet_end_to_end(
    prescription_api_client,
    monkeypatch,
    tmp_path,
):
    client, user, db = prescription_api_client

    # Keep uploaded encrypted files isolated inside pytest temp storage.
    # Isolate both storage roots while preserving production path structure.
    test_storage_root = tmp_path
    test_private_storage = test_storage_root / "prescriptions"

    monkeypatch.setattr(
    prescription_routes,
    "STORAGE_ROOT",
    test_storage_root,
)

    monkeypatch.setattr(
    prescription_routes,
    "PRIVATE_STORAGE",
    test_private_storage,
)

    # Mock OCR engine while preserving the real API processing flow.
    def mock_ocr(file_data, file_type):
        assert file_data
        assert file_type == "image/png"

        return {
            "engine": "test-ocr",
            "engine_version": "1.0",
            "languages": ["eng"],
            "page_count": 1,
            "pages": [],
            "full_text": (
                "Paracetamol 500 mg "
                "1 tablet twice daily for 5 days after food"
            ),
            "average_confidence": 0.99,
        }

    monkeypatch.setattr(
        prescription_routes,
        "process_prescription_ocr",
        mock_ocr,
    )

    # Deterministic extraction result; extraction API and persistence
    # remain real.
    extracted_medicine = ExtractedMedicine(
        medicine_name="Paracetamol",
        generic_name="Paracetamol",
        strength="500 mg",
        dosage_form="Tablet",
        dose="1 tablet",
        frequency="twice daily",
        duration="5 days",
        food_instruction="after food",
        source_text=(
            "Paracetamol 500 mg "
            "1 tablet twice daily for 5 days after food"
        ),
        verification_status="needs_review",
    )

    def mock_extraction(prescription_id, ocr_payload):
        assert prescription_id
        assert ocr_payload["full_text"]

        return SimpleNamespace(
            extraction_status="needs_review",
            medicines=[extracted_medicine],
            warnings=["User verification required."],
        )

    monkeypatch.setattr(
        prescription_routes,
        "extract_prescription_medicines",
        mock_extraction,
    )

    # Mock only the final Cabinet synchronization service.
    async def mock_sync(**kwargs):
        return {
            "prescription_id": kwargs["prescription_id"],
            "created_count": 1,
            "existing_count": 0,
            "catalog_matched_count": 0,
            "catalog_unmatched_count": 1,
        }

    monkeypatch.setattr(
        prescription_routes,
        "sync_confirmed_prescription",
        mock_sync,
    )

    # 1. Upload a PNG file.
    png_data = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 8
    )

    upload_response = await client.post(
        "/prescriptions/upload",
        files={
            "file": (
                "test-prescription.png",
                png_data,
                "image/png",
            )
        },
    )

    assert upload_response.status_code == 201

    prescription_id = upload_response.json()["prescription"]["id"]

    # 2. Process OCR.
    ocr_response = await client.post(
        f"/prescriptions/{prescription_id}/process"
    )
    print("\nOCR PROCESS RESPONSE:", ocr_response.status_code, ocr_response.text)
    assert ocr_response.status_code == 200
    assert ocr_response.json()["ocr"]["full_text"]

    # 3. Extract medicines.
    extraction_response = await client.post(
        f"/prescriptions/{prescription_id}/extract"
    )

    assert extraction_response.status_code == 200

    extraction_data = extraction_response.json()

    assert len(extraction_data["medicines"]) == 1
    assert extraction_data["requires_user_verification"] is True

    item_id = extraction_data["medicines"][0]["id"]

    # 4. Verify extracted medicine.
    verify_response = await client.put(
        f"/prescriptions/{prescription_id}/items/{item_id}/verify",
        json={
            "medicine_name": "Paracetamol",
            "generic_name": "Paracetamol",
            "strength": "500 mg",
            "dosage_form": "Tablet",
            "dose": "1 tablet",
            "frequency": "twice daily",
            "duration": "5 days",
            "food_instruction": "after food",
        },
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["verification_status"] == "verified"
    assert verify_response.json()["requires_final_user_confirmation"] is True

    # 5. Explicitly confirm prescription.
    confirm_response = await client.post(
        f"/prescriptions/{prescription_id}/confirm",
        json={"confirmed": True},
    )

    assert confirm_response.status_code == 200

    confirm_data = confirm_response.json()

    assert confirm_data["status"] == "confirmed"
    assert confirm_data["cabinet_sync_status"] == "completed"
    assert confirm_data["cabinet_created_count"] == 1
    assert confirm_data["medicine_count"] == 1

