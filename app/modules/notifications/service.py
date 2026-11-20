
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data, encrypt_data
from app.models.medication import MedicationLog
from app.models.notification import Notification


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def notification_aad(user_id: str, notification_id: str) -> bytes:
    return (
        f"medi:notification:v1:{user_id}:{notification_id}"
    ).encode("utf-8")


def encrypt_notification_payload(
    user_id: str,
    notification_id: str,
    payload: dict[str, Any],
) -> str:
    import json

    plaintext = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return encrypt_data(
        plaintext,
        associated_data=notification_aad(
            user_id,
            notification_id,
        ),
    )


def decrypt_notification_payload(
    notification: Notification,
) -> dict[str, Any]:
    import json

    plaintext = decrypt_data(
        notification.encrypted_payload,
        associated_data=notification_aad(
            notification.user_id,
            notification.id,
        ),
    )

    return json.loads(plaintext)


async def enqueue_dose_notifications(
    db: AsyncSession,
    user_id: str,
) -> int:
    """
    Create encrypted in-app notifications for pending medication doses.

    Notifications may be queued in advance, but must only be delivered
    when scheduled_at <= current UTC time.
    """

    result = await db.execute(
        select(MedicationLog).where(
            MedicationLog.user_id == user_id,
            MedicationLog.status == "pending",
        )
    )

    dose_logs = result.scalars().all()
    created_count = 0

    for dose_log in dose_logs:
        idempotency_key = (
            f"medication-dose:{dose_log.id}:in_app"
        )

        existing = await db.execute(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.idempotency_key == idempotency_key,
            )
        )

        if existing.scalar_one_or_none() is not None:
            continue

        notification_id = str(uuid.uuid4())

        payload = {
            "title": "Medication reminder",
            "message": "It is time to take your scheduled medication.",
            "dose_log_id": dose_log.id,
            "scheduled_at": dose_log.scheduled_at.isoformat(),
            "action": "medication_reminder",
        }

        notification = Notification(
            id=notification_id,
            user_id=user_id,
            medication_log_id=dose_log.id,
            channel="in_app",
            notification_type="medication_reminder",
            encrypted_payload=encrypt_notification_payload(
                user_id,
                notification_id,
                payload,
            ),
            status="pending",
            idempotency_key=idempotency_key,
            scheduled_at=dose_log.scheduled_at,
            attempts=0,
            max_attempts=5,
        )

        db.add(notification)
        created_count += 1

    await db.flush()
    return created_count


async def enqueue_missed_dose_notice(db: AsyncSession, user_id: str, missed_count: int) -> int:
    """Queue one generic, encrypted in-app summary per user per UTC day."""
    if missed_count <= 0:
        return 0
    day_key = utc_now().date().isoformat()
    idempotency_key = f"missed-dose-summary:{day_key}"
    existing = await db.execute(select(Notification.id).where(
        Notification.user_id == user_id,
        Notification.idempotency_key == idempotency_key,
    ))
    if existing.scalar_one_or_none() is not None:
        return 0
    notification_id = str(uuid.uuid4())
    db.add(Notification(
        id=notification_id, user_id=user_id, channel="in_app", notification_type="missed_dose",
        encrypted_payload=encrypt_notification_payload(user_id, notification_id, {
            "title": "Medication schedule update",
            "message": "A scheduled dose was marked missed. Review your medication schedule or contact your clinician if you are unsure what to do.",
            "action": "missed_dose_summary",
        }), status="pending", idempotency_key=idempotency_key,
        scheduled_at=utc_now(), attempts=0, max_attempts=5,
    ))
    await db.flush()
    return 1


async def get_due_notifications(
    db: AsyncSession,
    limit: int = 100,
) -> list[Notification]:
    """
    Return due in-app notifications.

    This function only reads due records. The worker must claim records
    safely before processing them when multiple workers are running.
    """

    now = utc_now()

    result = await db.execute(
        select(Notification)
        .where(
            Notification.channel == "in_app",
            Notification.status == "pending",
            Notification.scheduled_at <= now,
        )
        .order_by(Notification.scheduled_at.asc())
        .limit(limit)
    )

    return list(result.scalars().all())

from datetime import timedelta


async def claim_due_notifications(
    db: AsyncSession,
    limit: int = 100,
    lease_minutes: int = 5,
) -> list[Notification]:
    """
    Atomically claim due notifications for one worker.

    SKIP LOCKED prevents concurrent workers from claiming the same rows.
    Expired sending leases allow recovery after a worker crashes.
    """

    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    if not 1 <= lease_minutes <= 60:
        raise ValueError("lease_minutes must be between 1 and 60")

    now = utc_now()
    lease_expired_before = now - timedelta(minutes=lease_minutes)

    result = await db.execute(
        select(Notification)
        .where(
            Notification.channel == "in_app",
            Notification.scheduled_at <= now,
            (
    (Notification.next_retry_at.is_(None))
    | (Notification.next_retry_at <= now)
),
            (
                (Notification.status == "pending")
                | (
                    (Notification.status == "sending")
                    & (Notification.updated_at <= lease_expired_before)
                )
            ),
            Notification.attempts < Notification.max_attempts,
        )
        .order_by(Notification.scheduled_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    notifications = list(result.scalars().all())

    for notification in notifications:
        notification.status = "sending"
        notification.attempts += 1
        notification.updated_at = now

    await db.flush()
    return notifications




async def mark_notification_sent(
    db: AsyncSession,
    notification: Notification,
) -> None:
    notification.status = "sent"
    notification.sent_at = utc_now()
    notification.next_retry_at = None
    notification.last_error = None
    notification.updated_at = utc_now()
    await db.flush()


async def mark_notification_failed(
    db: AsyncSession,
    notification: Notification,
    error: str,
) -> None:
    now = utc_now()
    notification.last_error = error[:500]
    notification.updated_at = now

    if notification.attempts >= notification.max_attempts:
        notification.status = "failed"
        notification.next_retry_at = None
    else:
        notification.status = "pending"
        delay_seconds = min(
            3600,
            30 * (2 ** max(0, notification.attempts - 1)),
        )
        notification.next_retry_at = now + timedelta(
            seconds=delay_seconds
        )

    await db.flush()
