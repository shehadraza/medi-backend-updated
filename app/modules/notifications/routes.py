
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.modules.notifications.inbox_service import (
    get_unread_count,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.modules.notifications.schemas import (
    NotificationListResponse,
    NotificationUnreadCountResponse,
    NotificationReadResponse,
    NotificationReadAllResponse,
    HealthReminderRequest, HealthReminderResponse,
)
from app.models.notification import Notification
from app.models.medication import Prescription, MedicationLog
from app.models.health_profile import HealthProfile
from app.modules.notifications.service import encrypt_notification_payload
import uuid

router = APIRouter(
    prefix="/notifications",
    tags=["Notification Inbox"],
)


@router.post("/health-reminders", response_model=HealthReminderResponse, status_code=201)
async def create_health_reminder(
    payload: HealthReminderRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a user-requested encrypted in-app reminder; no external channel is implied."""
    user_id = str(current_user.id)
    if (payload.reminder_kind == "prescription_followup") != (payload.prescription_id is not None):
        raise HTTPException(status_code=422, detail="A prescription follow-up requires a confirmed prescription.")
    if payload.prescription_id:
        prescription = await db.execute(select(Prescription.id).where(
            Prescription.id == payload.prescription_id,
            Prescription.user_id == user_id,
            Prescription.confirmed_at.is_not(None),
        ))
        if prescription.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Confirmed prescription not found.")
    idempotency_key = f"{payload.reminder_kind}:{payload.idempotency_key}"
    existing = await db.execute(select(Notification).where(
        Notification.user_id == user_id,
        Notification.idempotency_key == idempotency_key,
    ))
    row = existing.scalar_one_or_none()
    if row:
        return {"notification_id": row.id, "scheduled_at": row.scheduled_at}
    notification_id = str(uuid.uuid4())
    row = Notification(
        id=notification_id, user_id=user_id, channel="in_app", notification_type="general",
        encrypted_payload=encrypt_notification_payload(user_id, notification_id, {
            "title": "Health reminder", "message": payload.message,
            "action": "user_requested_reminder", "prescription_id": payload.prescription_id,
        }), status="pending", idempotency_key=idempotency_key,
        scheduled_at=payload.scheduled_at, attempts=0, max_attempts=5,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Concurrent duplicate requests return a generic conflict; callers can safely retry.
        raise HTTPException(status_code=409, detail="Reminder could not be created with this request key.") from exc
    return {"notification_id": notification_id, "scheduled_at": payload.scheduled_at}


@router.post("/adherence-summary", response_model=HealthReminderResponse, status_code=201)
async def create_adherence_summary(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly requested 30-day aggregate, gated by personalization consent."""
    user_id = str(current_user.id)
    profile_result = await db.execute(select(HealthProfile).where(
        HealthProfile.user_id == user_id,
    ).with_for_update())
    profile = profile_result.scalar_one_or_none()
    if profile is None or profile.ai_personalization_consent is not True:
        raise HTTPException(status_code=403, detail="Personalization consent is required for an adherence summary.")
    now = datetime.now(timezone.utc)
    rows = await db.execute(select(MedicationLog.status, func.count()).where(
        MedicationLog.user_id == user_id,
        MedicationLog.scheduled_at >= now - timedelta(days=30),
        MedicationLog.scheduled_at <= now,
    ).group_by(MedicationLog.status))
    counts = {str(status): int(count) for status, count in rows.all()}
    day = now.date().isoformat()
    key = f"adherence-summary:{day}"
    existing = await db.execute(select(Notification).where(Notification.user_id == user_id, Notification.idempotency_key == key))
    prior = existing.scalar_one_or_none()
    if prior:
        return {"notification_id": prior.id, "scheduled_at": prior.scheduled_at}
    notification_id = str(uuid.uuid4())
    db.add(Notification(
        id=notification_id, user_id=user_id, channel="in_app", notification_type="general",
        encrypted_payload=encrypt_notification_payload(user_id, notification_id, {
            "title": "Your medication adherence summary",
            "message": "Last 30 days: " + ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())) + ". This summary reflects recorded logs and may be incomplete.",
            "action": "adherence_summary", "period_days": 30,
        }), status="pending", idempotency_key=key, scheduled_at=now, attempts=0, max_attempts=5,
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        prior_result = await db.execute(select(Notification).where(
            Notification.user_id == user_id,
            Notification.idempotency_key == key,
        ))
        prior = prior_result.scalar_one_or_none()
        if prior is not None:
            return {"notification_id": prior.id, "scheduled_at": prior.scheduled_at}
        raise HTTPException(status_code=503, detail="Adherence summary is temporarily unavailable.")
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail="Adherence summary is temporarily unavailable.") from exc
    return {"notification_id": notification_id, "scheduled_at": now}


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/unread-count",
    response_model=NotificationUnreadCountResponse,
)
async def get_notifications_unread_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await get_unread_count(
        db=db,
        user_id=current_user.id,
    )
    return {"unread_count": count}


@router.post(
    "/read-all",
    response_model=NotificationReadAllResponse,
)
async def read_all_notifications(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await mark_all_notifications_read(
        db=db,
        user_id=current_user.id,
    )
    await db.commit()
    return result


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationReadResponse,
)
async def read_notification(
    notification_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await mark_notification_read(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    await db.commit()
    return result
