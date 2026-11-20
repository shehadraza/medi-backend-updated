
from __future__ import annotations

import json
import uuid

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data, encrypt_data
from app.models.medication import Medication, MedicationSchedule


def schedule_aad(user_id: str, schedule_id: str) -> bytes:
    return (
        f"medi:medication-schedule:v1:{user_id}:{schedule_id}"
    ).encode("utf-8")


def encrypt_schedule(
    user_id: str,
    schedule_id: str,
    data: dict,
) -> str:
    return encrypt_data(
        json.dumps(data, ensure_ascii=False),
        associated_data=schedule_aad(user_id, schedule_id),
    )


def decrypt_schedule(schedule: MedicationSchedule) -> dict:
    try:
        plaintext = decrypt_data(
            schedule.encrypted_schedule,
            associated_data=schedule_aad(
                schedule.user_id,
                schedule.id,
            ),
        )
        return json.loads(plaintext)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to securely read medication schedule.",
        ) from exc


async def get_owned_medication(
    db: AsyncSession,
    user_id: str,
    medication_id: str,
) -> Medication:
    result = await db.execute(
        select(Medication).where(
            Medication.id == medication_id,
            Medication.user_id == user_id,
            Medication.status == "active",
        )
    )

    medication = result.scalar_one_or_none()

    if medication is None:
        raise HTTPException(
            status_code=404,
            detail="Active medication not found.",
        )

    return medication


def calculate_next_dose(
    data: dict,
    now: datetime | None = None,
) -> datetime | None:
    now = now or datetime.now(timezone.utc)

    tz = ZoneInfo(data["timezone_name"])
    local_now = now.astimezone(tz)

    start_date = (
        date.fromisoformat(data["start_date"])
        if data.get("start_date")
        else None
    )

    end_date = (
        date.fromisoformat(data["end_date"])
        if data.get("end_date")
        else None
    )

    if end_date and local_now.date() > end_date:
        return None

    if start_date and local_now.date() < start_date:
        candidate_date = start_date
    else:
        candidate_date = local_now.date()

    recurrence = data["recurrence"]
    weekdays = set(data.get("weekdays", []))

    # Search the next 8 days to find the next valid scheduled dose.
    for day_offset in range(8):
        current_date = candidate_date + timedelta(days=day_offset)

        if end_date and current_date > end_date:
            return None

        if start_date and current_date < start_date:
            continue

        if recurrence == "weekly" and current_date.weekday() not in weekdays:
            continue

        for time_string in sorted(data["reminder_times"]):
            scheduled_time = time.fromisoformat(time_string)

            candidate = datetime.combine(
                current_date,
                scheduled_time,
                tzinfo=tz,
            )

            if candidate > local_now:
                return candidate.astimezone(timezone.utc)

    return None


async def create_medication_schedule(
    db: AsyncSession,
    user_id: str,
    payload,
) -> MedicationSchedule:
    medication = await get_owned_medication(
        db,
        user_id,
        payload.medication_id,
    )

    existing = await db.execute(
        select(MedicationSchedule).where(
            MedicationSchedule.medication_id == medication.id,
            MedicationSchedule.user_id == user_id,
            MedicationSchedule.is_active.is_(True),
        )
    )

    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="An active reminder schedule already exists for this medication.",
        )

    schedule_id = str(uuid.uuid4())

    data = {
        "reminder_times": [
            item.isoformat(timespec="minutes")
            for item in payload.reminder_times
        ],
        "recurrence": payload.recurrence,
        "weekdays": payload.weekdays,
        "timezone_name": payload.timezone_name,
        "start_date": (
            payload.start_date.isoformat()
            if payload.start_date
            else None
        ),
        "end_date": (
            payload.end_date.isoformat()
            if payload.end_date
            else None
        ),
        "reminder_enabled": payload.reminder_enabled,
    }

    next_dose = (
        calculate_next_dose(data)
        if payload.reminder_enabled
        else None
    )

    schedule = MedicationSchedule(
        id=schedule_id,
        medication_id=medication.id,
        user_id=user_id,
        encrypted_schedule=encrypt_schedule(
            user_id,
            schedule_id,
            data,
        ),
        next_dose_at=next_dose,
        is_active=payload.reminder_enabled,
    )

    db.add(schedule)
    await db.flush()

    return schedule


async def update_medication_schedule(
    db: AsyncSession,
    user_id: str,
    schedule_id: str,
    changes: dict,
) -> MedicationSchedule:
    result = await db.execute(
        select(MedicationSchedule).where(
            MedicationSchedule.id == schedule_id,
            MedicationSchedule.user_id == user_id,
        )
    )

    schedule = result.scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=404,
            detail="Medication schedule not found.",
        )

    data = decrypt_schedule(schedule)

    for field, value in changes.items():
        if field == "reminder_times" and value is not None:
            data[field] = [
                item.isoformat(timespec="minutes")
                if isinstance(item, time)
                else item
                for item in value
            ]

        elif field in {"start_date", "end_date"}:
            data[field] = value.isoformat() if value else None

        elif value is not None:
            data[field] = value

    if (
        data.get("start_date")
        and data.get("end_date")
        and data["end_date"] < data["start_date"]
    ):
        raise HTTPException(
            status_code=422,
            detail="End date cannot be before start date.",
        )

    if data["recurrence"] == "weekly" and not data["weekdays"]:
        raise HTTPException(
            status_code=422,
            detail="Weekly schedule requires at least one weekday.",
        )

    if data["recurrence"] == "daily" and data["weekdays"]:
        raise HTTPException(
            status_code=422,
            detail="Daily schedules cannot contain selected weekdays.",
        )

    enabled = data["reminder_enabled"]

    schedule.encrypted_schedule = encrypt_schedule(
        user_id,
        schedule.id,
        data,
    )

    schedule.is_active = enabled
    schedule.next_dose_at = (
        calculate_next_dose(data)
        if enabled
        else None
    )

    schedule.updated_at = datetime.now(timezone.utc)

    await db.flush()

    return schedule


async def disable_medication_schedule(
    db: AsyncSession,
    user_id: str,
    schedule_id: str,
) -> MedicationSchedule:
    result = await db.execute(
        select(MedicationSchedule).where(
            MedicationSchedule.id == schedule_id,
            MedicationSchedule.user_id == user_id,
        )
    )

    schedule = result.scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=404,
            detail="Medication schedule not found.",
        )

    schedule.is_active = False
    schedule.next_dose_at = None

    data = decrypt_schedule(schedule)
    data["reminder_enabled"] = False

    schedule.encrypted_schedule = encrypt_schedule(
        user_id,
        schedule.id,
        data,
    )

    schedule.updated_at = datetime.now(timezone.utc)

    await db.flush()

    return schedule
