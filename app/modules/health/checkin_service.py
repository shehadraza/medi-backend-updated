"""CRUD and AES-GCM handling for user-owned daily health check-ins."""

import json
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data, encrypt_data
from app.models.health_checkin import DailyHealthCheckIn


ENCRYPTION_VERSION = 1
_DATA_FIELDS = (
    "sleep_duration_hours", "sleep_quality", "water_intake_liters",
    "physical_activity", "physical_activity_minutes", "screen_time_hours",
    "eating_habits", "junk_food_portions", "wellbeing_level", "energy_level",
    "symptoms", "notes",
)


def checkin_aad(checkin_id: str, user_id: str, local_date: date) -> bytes:
    if not checkin_id or not user_id or not isinstance(local_date, date):
        raise ValueError("Valid check-in identity is required.")
    return f"medi:daily-health-checkin:v1:{checkin_id}:{user_id}:{local_date.isoformat()}".encode()


def _encrypt(data: dict, *, checkin_id: str, user_id: str, local_date: date) -> str:
    try:
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Check-in data is invalid.") from exc
    return encrypt_data(serialized, associated_data=checkin_aad(checkin_id, user_id, local_date))


def _decrypt(record: DailyHealthCheckIn) -> dict:
    if record.encryption_version != ENCRYPTION_VERSION:
        raise HTTPException(status_code=503, detail="Check-in data is temporarily unavailable.")
    try:
        value = json.loads(decrypt_data(
            record.encrypted_data,
            associated_data=checkin_aad(record.id, record.user_id, record.local_date),
        ))
    except Exception as exc:
        # Do not include ciphertext, plaintext, or cryptographic details in errors.
        raise HTTPException(status_code=503, detail="Check-in data is temporarily unavailable.") from None
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="Check-in data is temporarily unavailable.")
    return value


def _response(record: DailyHealthCheckIn) -> dict:
    return {
        "id": record.id,
        "local_date": record.local_date,
        "timezone_name": record.timezone_name,
        "data": _decrypt(record),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _reject_future_date(local_date: date, timezone_name: str) -> None:
    if local_date > datetime.now(ZoneInfo(timezone_name)).date():
        raise HTTPException(status_code=422, detail="Future check-in dates are not allowed.")




async def create_checkin(db: AsyncSession, user_id: str, payload) -> dict:
    _reject_future_date(payload.local_date, payload.timezone_name)

    record_id = str(uuid.uuid4())
    data = payload.model_dump(include=set(_DATA_FIELDS), exclude_unset=True)

    record = DailyHealthCheckIn(
        id=record_id,
        user_id=user_id,
        local_date=payload.local_date,
        timezone_name=payload.timezone_name,
        encrypted_data=_encrypt(
            data,
            checkin_id=record_id,
            user_id=user_id,
            local_date=payload.local_date,
        ),
        encryption_version=ENCRYPTION_VERSION,
    )

    try:
        # Only this insert is rolled back on a duplicate.
        async with db.begin_nested():
            db.add(record)
            await db.flush()

    except IntegrityError as exc:
        original = getattr(exc, "orig", None)

        def find_constraint_name(error):
            seen = set()
            current = error

            while current is not None and id(current) not in seen:
                seen.add(id(current))

                name = getattr(current, "constraint_name", None)
                if name:
                    return name

                diagnostic = getattr(current, "diag", None)
                name = getattr(diagnostic, "constraint_name", None)
                if name:
                    return name

                current = (
                    getattr(current, "__cause__", None)
                    or getattr(current, "__context__", None)
                    or getattr(current, "orig", None)
                )

            return None

        constraint_name = find_constraint_name(original)

        if constraint_name == "uq_daily_health_checkins_user_date":
            raise HTTPException(
                status_code=409,
                detail="A check-in already exists for this local date.",
            ) from None

        raise HTTPException(
            status_code=503,
            detail="Check-in service is temporarily unavailable.",
        ) from None

    return _response(record)




async def get_checkin(db: AsyncSession, user_id: str, checkin_id: str) -> dict:
    result = await db.execute(select(DailyHealthCheckIn).where(
        DailyHealthCheckIn.id == checkin_id,
        DailyHealthCheckIn.user_id == user_id,
    ))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Check-in not found.")
    return _response(record)


async def list_checkins(
    db: AsyncSession, user_id: str, *, start_date: date | None, end_date: date | None,
    limit: int, offset: int,
) -> list[dict]:
    query = select(DailyHealthCheckIn).where(DailyHealthCheckIn.user_id == user_id)
    if start_date is not None:
        query = query.where(DailyHealthCheckIn.local_date >= start_date)
    if end_date is not None:
        query = query.where(DailyHealthCheckIn.local_date <= end_date)
    query = query.order_by(DailyHealthCheckIn.local_date.desc()).limit(limit).offset(offset)
    records = (await db.execute(query)).scalars().all()
    return [_response(record) for record in records]


async def update_checkin(db: AsyncSession, user_id: str, checkin_id: str, payload) -> dict:
    result = await db.execute(select(DailyHealthCheckIn).where(
        DailyHealthCheckIn.id == checkin_id,
        DailyHealthCheckIn.user_id == user_id,
    ).with_for_update())
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Check-in not found.")
    data = _decrypt(record)
    data.update(payload.model_dump(exclude_unset=True))
    record.encrypted_data = _encrypt(
        data, checkin_id=record.id, user_id=record.user_id, local_date=record.local_date,
    )
    record.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _response(record)


async def delete_checkin(db: AsyncSession, user_id: str, checkin_id: str) -> None:
    result = await db.execute(select(DailyHealthCheckIn).where(
        DailyHealthCheckIn.id == checkin_id,
        DailyHealthCheckIn.user_id == user_id,
    ).with_for_update())
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Check-in not found.")
    await db.delete(record)
    await db.flush()
