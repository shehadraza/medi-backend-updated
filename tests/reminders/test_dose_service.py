
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models.user import User
from app.models.medication import Medication, MedicationSchedule, MedicationLog
from app.modules.reminders.service import encrypt_schedule
from app.modules.reminders.dose_service import (
    generate_due_doses,
    mark_dose,
    mark_missed_doses,
    get_adherence,
)


@pytest_asyncio.fixture
async def reminder_db():
    user_id = str(uuid.uuid4())

    async with engine.connect() as connection:
        transaction = await connection.begin()

        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as db:
                user = User(
                    id=user_id,
                    full_name="MEDI Reminder Test",
                    email=f"reminder-test-{user_id}@example.com",
                    password_hash="test-only-not-a-real-password",
                    is_active=True,
                    is_verified=True,
                )

                db.add(user)
                await db.flush()

                yield db, user

        finally:
            if transaction.is_active:
                await transaction.rollback()


async def create_medication(db, user):
    medication = Medication(
        id=str(uuid.uuid4()),
        user_id=user.id,
        encrypted_data="test-encrypted-medication-data",
        status="active",
    )

    db.add(medication)
    await db.flush()

    return medication


async def create_schedule(
    db,
    user,
    medication,
    reminder_times=None,
    recurrence="daily",
    weekdays=None,
):
    schedule_id = str(uuid.uuid4())

    data = {
        "reminder_times": reminder_times or ["08:30"],
        "recurrence": recurrence,
        "weekdays": weekdays or [],
        "timezone_name": "Asia/Dhaka",
        "start_date": None,
        "end_date": None,
        "reminder_enabled": True,
    }

    schedule = MedicationSchedule(
        id=schedule_id,
        medication_id=medication.id,
        user_id=user.id,
        encrypted_schedule=encrypt_schedule(
            user.id,
            schedule_id,
            data,
        ),
        is_active=True,
    )

    db.add(schedule)
    await db.flush()

    return schedule


@pytest.mark.asyncio
async def test_generate_due_doses_prevents_duplicates(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    dhaka = ZoneInfo("Asia/Dhaka")
    target = (
        datetime.now(dhaka) + timedelta(minutes=5)
    ).replace(second=0, microsecond=0)

    schedule = await create_schedule(
        db,
        user,
        medication,
        reminder_times=[target.strftime("%H:%M")],
    )

    # Restrict this schedule to the target local date.
    from app.modules.reminders.service import decrypt_schedule

    data = decrypt_schedule(schedule)
    data["start_date"] = target.date().isoformat()

    schedule.encrypted_schedule = encrypt_schedule(
        user.id,
        schedule.id,
        data,
    )

    first_count = await generate_due_doses(
        db,
        user.id,
        horizon_minutes=30,
        lookback_minutes=5,
    )

    second_count = await generate_due_doses(
        db,
        user.id,
        horizon_minutes=30,
        lookback_minutes=5,
    )

    assert first_count == 1
    assert second_count == 0

    result = await db.execute(
        select(MedicationLog).where(
            MedicationLog.schedule_id == schedule.id
        )
    )

    logs = result.scalars().all()

    assert len(logs) == 1
    assert logs[0].status == "pending"

    expected_utc = target.astimezone(timezone.utc)

    actual_utc = logs[0].scheduled_at
    if actual_utc.tzinfo is None:
        actual_utc = actual_utc.replace(tzinfo=timezone.utc)

    assert actual_utc == expected_utc


@pytest.mark.asyncio
async def test_mark_dose_taken_and_prevent_repeated_action(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    log = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=datetime.now(timezone.utc),
        status="pending",
    )

    db.add(log)
    await db.flush()

    updated = await mark_dose(
        db,
        user.id,
        log.id,
        "taken",
    )

    assert updated.status == "taken"
    assert updated.taken_at is not None

    with pytest.raises(HTTPException) as error:
        await mark_dose(
            db,
            user.id,
            log.id,
            "skipped",
        )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_mark_dose_skipped_has_no_taken_timestamp(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    log = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=datetime.now(timezone.utc),
        status="pending",
    )

    db.add(log)
    await db.flush()

    updated = await mark_dose(
        db,
        user.id,
        log.id,
        "skipped",
    )

    assert updated.status == "skipped"
    assert updated.taken_at is None


@pytest.mark.asyncio
async def test_mark_dose_rejects_another_users_log(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    log = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=datetime.now(timezone.utc),
        status="pending",
    )

    db.add(log)
    await db.flush()

    with pytest.raises(HTTPException) as error:
        await mark_dose(
            db,
            str(uuid.uuid4()),
            log.id,
            "taken",
        )

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_missed_doses_respects_grace_period(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    overdue = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=3),
        status="pending",
    )

    recent = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        status="pending",
    )

    db.add_all([overdue, recent])
    await db.flush()

    count = await mark_missed_doses(
        db,
        user.id,
        grace_minutes=120,
    )

    assert count == 1
    assert overdue.status == "missed"
    assert recent.status == "pending"


@pytest.mark.asyncio
async def test_adherence_excludes_pending_from_percentage(reminder_db):
    db, user = reminder_db

    medication = await create_medication(db, user)

    statuses = [
        "taken",
        "taken",
        "skipped",
        "missed",
        "pending",
    ]

    now = datetime.now(timezone.utc)

    logs = [
        MedicationLog(
            id=str(uuid.uuid4()),
            medication_id=medication.id,
            schedule_id=None,
            user_id=user.id,
            scheduled_at=now + timedelta(minutes=index),
            status=status,
            taken_at=now if status == "taken" else None,
        )
        for index, status in enumerate(statuses)
    ]

    db.add_all(logs)
    await db.flush()

    result = await get_adherence(db, user.id)

    assert result["total_doses"] == 5
    assert result["taken"] == 2
    assert result["skipped"] == 1
    assert result["missed"] == 1
    assert result["pending"] == 1

    # 2 taken / (2 taken + 1 skipped + 1 missed) = 50%
    assert result["adherence_percentage"] == 50.0


@pytest.mark.asyncio
async def test_generate_due_doses_rejects_invalid_horizon(reminder_db):
    db, user = reminder_db

    with pytest.raises(HTTPException) as error:
        await generate_due_doses(
            db,
            user.id,
            horizon_minutes=0,
        )

    assert error.value.status_code == 422
