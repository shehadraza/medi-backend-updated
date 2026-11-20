from datetime import date, datetime, timedelta
import uuid
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import HTTPException
from cryptography.exceptions import InvalidTag
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.encryption import decrypt_data, encrypt_data
from app.db.session import engine, get_db
from app.main import app
from app.models.health_checkin import DailyHealthCheckIn
from app.models.health_profile import HealthProfile
from app.models.user import User
from app.modules.health.checkin_schemas import CheckInCreateRequest, CheckInPatchRequest
from app.modules.health.checkin_service import (
    _decrypt, checkin_aad, create_checkin, delete_checkin, get_checkin,
    list_checkins, update_checkin,
)


@pytest_asyncio.fixture
async def checkin_db():
    owner = User(
        id=str(uuid.uuid4()), full_name="Check-in Owner",
        email=f"checkin-{uuid.uuid4()}@example.test", password_hash="test-only-hash",
        is_active=True, is_verified=True,
    )
    other = User(
        id=str(uuid.uuid4()), full_name="Other Owner",
        email=f"checkin-other-{uuid.uuid4()}@example.test", password_hash="test-only-hash",
        is_active=True, is_verified=True,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
            ) as db:
                db.add_all([owner, other])
                await db.flush()
                profile = HealthProfile(
                    user_id=owner.id, encrypted_data="profile-ciphertext",
                    ai_personalization_consent=False,
                    proactive_health_analysis_consent=False,
                    proactive_wellness_notifications_consent=False,
                )
                db.add(profile)
                await db.flush()
                yield db, owner, other, profile
        finally:
            app.dependency_overrides.clear()
            if transaction.is_active:
                await transaction.rollback()


def _create_payload(**overrides):
    values = {
        "local_date": datetime.now(ZoneInfo("Asia/Dhaka")).date(),
        "timezone_name": "Asia/Dhaka",
        "sleep_duration_hours": 7.5,
        "notes": "private check-in note",
    }
    values.update(overrides)
    return CheckInCreateRequest(**values)


def test_schema_accepts_partial_and_rejects_invalid_ranges_and_timezone():
    payload = CheckInCreateRequest(
        local_date=date.today(), timezone_name="Asia/Dhaka", water_intake_liters=1.5,
    )
    assert payload.water_intake_liters == 1.5
    with pytest.raises(ValueError):
        CheckInCreateRequest(local_date=date.today(), timezone_name="Asia/Dhaka")
    with pytest.raises(ValueError):
        _create_payload(sleep_duration_hours=25)
    with pytest.raises(ValueError):
        _create_payload(timezone_name="Not/A_Zone")
    with pytest.raises(ValueError):
        _create_payload(unexpected="value")
    with pytest.raises(ValueError):
        CheckInPatchRequest()


def test_encryption_aad_is_bound_to_record_owner_and_date():
    day = date(2026, 11, 18)
    aad = checkin_aad("record", "owner", day)
    assert b"record" in aad and b"owner" in aad and b"2026-11-18" in aad
    assert aad != checkin_aad("record", "other", day)
    assert aad != checkin_aad("record", "owner", date(2026, 11, 19))
    encrypted = encrypt_data("private", associated_data=aad)
    assert decrypt_data(encrypted, associated_data=aad) == "private"
    with pytest.raises(InvalidTag):
        decrypt_data(encrypted, associated_data=checkin_aad("record", "other", day))


@pytest.mark.asyncio
async def test_create_encrypts_fields_and_does_not_change_consent(checkin_db):
    db, owner, _, profile = checkin_db
    result = await create_checkin(db, owner.id, _create_payload())
    record = await db.get(DailyHealthCheckIn, result["id"])
    assert "private check-in note" not in record.encrypted_data
    assert "7.5" not in record.encrypted_data
    assert _decrypt(record)["notes"] == "private check-in note"
    await db.refresh(profile)
    assert profile.ai_personalization_consent is False
    assert profile.proactive_health_analysis_consent is False
    assert profile.proactive_wellness_notifications_consent is False


@pytest.mark.asyncio
async def test_duplicate_same_owner_date_returns_conflict_without_overwrite(checkin_db):
    db, owner, _, _ = checkin_db
    payload = _create_payload()
    original = await create_checkin(db, owner.id, payload)
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await create_checkin(db, owner.id, payload)
    assert error.value.status_code == 409
    found = await get_checkin(db, owner.id, original["id"])
    assert found["data"]["notes"] == "private check-in note"


@pytest.mark.asyncio
async def test_patch_preserves_omitted_fields_and_null_clears_supplied_field(checkin_db):
    db, owner, _, _ = checkin_db
    created = await create_checkin(db, owner.id, _create_payload())
    updated = await update_checkin(
        db, owner.id, created["id"], CheckInPatchRequest(sleep_duration_hours=6.0, notes=None),
    )
    assert updated["data"]["sleep_duration_hours"] == 6.0
    assert updated["data"]["notes"] is None
    assert "water_intake_liters" not in updated["data"]
    assert updated["local_date"] == created["local_date"]
    assert updated["timezone_name"] == created["timezone_name"]


@pytest.mark.asyncio
async def test_future_local_date_is_rejected_and_historical_date_allowed(checkin_db):
    db, owner, _, _ = checkin_db
    tomorrow = datetime.now(ZoneInfo("Asia/Dhaka")).date() + timedelta(days=1)
    with pytest.raises(HTTPException) as error:
        await create_checkin(db, owner.id, _create_payload(local_date=tomorrow))
    assert error.value.status_code == 422
    old = await create_checkin(db, owner.id, _create_payload(local_date=date(2020, 1, 1)))
    assert old["local_date"] == date(2020, 1, 1)


@pytest.mark.asyncio
async def test_owner_scoped_retrieve_list_update_and_delete(checkin_db):
    db, owner, other, _ = checkin_db
    created = await create_checkin(db, owner.id, _create_payload())
    with pytest.raises(HTTPException) as error:
        await get_checkin(db, other.id, created["id"])
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await update_checkin(db, other.id, created["id"], CheckInPatchRequest(notes="wrong owner"))
    owner_items = await list_checkins(db, owner.id, start_date=None, end_date=None, limit=30, offset=0)
    other_items = await list_checkins(db, other.id, start_date=None, end_date=None, limit=30, offset=0)
    assert [item["id"] for item in owner_items] == [created["id"]]
    assert other_items == []
    with pytest.raises(HTTPException):
        await delete_checkin(db, other.id, created["id"])
    await delete_checkin(db, owner.id, created["id"])
    assert (await db.execute(select(DailyHealthCheckIn).where(
        DailyHealthCheckIn.id == created["id"], DailyHealthCheckIn.user_id == owner.id,
    ))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_authenticated_api_returns_conflict_and_hides_other_users_rows(checkin_db):
    db, owner, other, _ = checkin_db
    current = {"user": owner}

    async def current_user():
        return current["user"]

    async def current_db():
        yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            body = {
    "local_date": datetime.now(ZoneInfo("Asia/Dhaka")).date().isoformat(),
    "timezone_name": "Asia/Dhaka",
    "water_intake_liters": 1.25,
}
            first = await client.post("/health/check-ins", json=body)
            assert first.status_code == 201
            second = await client.post("/health/check-ins", json=body)
            assert second.status_code == 409
            current["user"] = other
            other_user_read = await client.get(f"/health/check-ins/{first.json()['id']}")
            assert other_user_read.status_code == 404
    finally:
        app.dependency_overrides.clear()
