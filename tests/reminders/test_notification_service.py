
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models.user import User
from app.models.medication import Medication, MedicationLog
from app.models.notification import Notification
from app.modules.notifications.service import (
    claim_due_notifications,
    decrypt_notification_payload,
    encrypt_notification_payload,
    enqueue_dose_notifications,
    mark_notification_failed,
    mark_notification_sent,
)


@pytest_asyncio.fixture
async def notification_db():
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
                    full_name="MEDI Notification Test",
                    email=f"notification-test-{user_id}@example.com",
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


async def create_dose_log(
    db,
    user,
    medication,
    status="pending",
    scheduled_at=None,
):
    log = MedicationLog(
        id=str(uuid.uuid4()),
        medication_id=medication.id,
        schedule_id=None,
        user_id=user.id,
        scheduled_at=scheduled_at or datetime.now(timezone.utc),
        status=status,
    )

    db.add(log)
    await db.flush()

    return log


@pytest.mark.asyncio
async def test_notification_payload_encryption(notification_db):
    db, user = notification_db

    notification_id = str(uuid.uuid4())

    payload = {
        "title": "Medication reminder",
        "message": "Time to take your medicine",
        "medicine_name": "Test Medicine",
    }

    encrypted = encrypt_notification_payload(
        user.id,
        notification_id,
        payload,
    )

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypted,
        status="pending",
        idempotency_key=f"test:{notification_id}",
        scheduled_at=datetime.now(timezone.utc),
        attempts=0,
        max_attempts=5,
    )

    assert encrypted != str(payload)

    decrypted = decrypt_notification_payload(notification)

    assert decrypted == payload


@pytest.mark.asyncio
async def test_enqueue_creates_notification_for_pending_dose(
    notification_db,
):
    db, user = notification_db

    medication = await create_medication(db, user)

    log = await create_dose_log(
        db,
        user,
        medication,
        scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    count = await enqueue_dose_notifications(db, user.id)

    assert count == 1

    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.medication_log_id == log.id,
        )
    )

    notification = result.scalar_one()

    assert notification.channel == "in_app"
    assert notification.status == "pending"
    assert notification.scheduled_at == log.scheduled_at

    payload = decrypt_notification_payload(notification)

    assert payload["dose_log_id"] == log.id
    assert payload["action"] == "medication_reminder"


@pytest.mark.asyncio
async def test_enqueue_prevents_duplicate_notifications(
    notification_db,
):
    db, user = notification_db

    medication = await create_medication(db, user)

    await create_dose_log(
        db,
        user,
        medication,
    )

    first_count = await enqueue_dose_notifications(db, user.id)
    second_count = await enqueue_dose_notifications(db, user.id)

    assert first_count == 1
    assert second_count == 0

    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user.id,
        )
    )

    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_enqueue_ignores_non_pending_doses(notification_db):
    db, user = notification_db

    medication = await create_medication(db, user)

    await create_dose_log(
        db,
        user,
        medication,
        status="taken",
    )

    await create_dose_log(
        db,
        user,
        medication,
        status="skipped",
    )

    await create_dose_log(
        db,
        user,
        medication,
        status="missed",
    )

    count = await enqueue_dose_notifications(db, user.id)

    assert count == 0


@pytest.mark.asyncio
async def test_claim_due_notifications_ignores_future_notifications(
    notification_db,
):
    db, user = notification_db

    now = datetime.now(timezone.utc)

    due_id = str(uuid.uuid4())
    future_id = str(uuid.uuid4())

    due = Notification(
        id=due_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            due_id,
            {"title": "Due"},
        ),
        status="pending",
        idempotency_key=f"test:{due_id}",
        scheduled_at=now - timedelta(minutes=1),
        attempts=0,
        max_attempts=5,
    )

    future = Notification(
        id=future_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            future_id,
            {"title": "Future"},
        ),
        status="pending",
        idempotency_key=f"test:{future_id}",
        scheduled_at=now + timedelta(hours=1),
        attempts=0,
        max_attempts=5,
    )

    db.add_all([due, future])
    await db.flush()

    claimed = await claim_due_notifications(db, limit=10)

    claimed_ids = {item.id for item in claimed}

    assert due_id in claimed_ids
    assert future_id not in claimed_ids
    assert due.status == "sending"
    assert due.attempts == 1
    assert future.status == "pending"


@pytest.mark.asyncio
async def test_mark_notification_sent(notification_db):
    db, user = notification_db

    notification_id = str(uuid.uuid4())

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            notification_id,
            {"title": "Test"},
        ),
        status="sending",
        idempotency_key=f"test:{notification_id}",
        scheduled_at=datetime.now(timezone.utc),
        attempts=1,
        max_attempts=5,
    )

    db.add(notification)
    await db.flush()

    await mark_notification_sent(db, notification)

    assert notification.status == "sent"
    assert notification.sent_at is not None
    assert notification.next_retry_at is None
    assert notification.last_error is None


@pytest.mark.asyncio
async def test_mark_notification_failed_schedules_retry(
    notification_db,
):
    db, user = notification_db

    notification_id = str(uuid.uuid4())

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            notification_id,
            {"title": "Test"},
        ),
        status="sending",
        idempotency_key=f"test:{notification_id}",
        scheduled_at=datetime.now(timezone.utc),
        attempts=1,
        max_attempts=5,
    )

    db.add(notification)
    await db.flush()

    await mark_notification_failed(
        db,
        notification,
        "Temporary test failure",
    )

    assert notification.status == "pending"
    assert notification.next_retry_at is not None
    assert notification.last_error == "Temporary test failure"


@pytest.mark.asyncio
async def test_mark_notification_failed_stops_after_max_attempts(
    notification_db,
):
    db, user = notification_db

    notification_id = str(uuid.uuid4())

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        channel="in_app",
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            notification_id,
            {"title": "Test"},
        ),
        status="sending",
        idempotency_key=f"test:{notification_id}",
        scheduled_at=datetime.now(timezone.utc),
        attempts=5,
        max_attempts=5,
    )

    db.add(notification)
    await db.flush()

    await mark_notification_failed(
        db,
        notification,
        "Maximum retries reached",
    )

    assert notification.status == "failed"
    assert notification.next_retry_at is None
