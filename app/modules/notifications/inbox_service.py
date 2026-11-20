
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.modules.notifications.schemas import (
    NotificationItem,
)
from app.modules.notifications.service import (
    decrypt_notification_payload,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_unread_count(
    db: AsyncSession,
    user_id: str,
) -> int:
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.channel == "in_app",
            Notification.status == "sent",
            Notification.read_at.is_(None),
        )
    )
    return result.scalar_one()


async def list_notifications(
    db: AsyncSession,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
):
    filters = (
        Notification.user_id == user_id,
        Notification.channel == "in_app",
        Notification.status == "sent",
    )

    total_result = await db.execute(
        select(func.count(Notification.id)).where(*filters)
    )
    total = total_result.scalar_one()

    unread_count = await get_unread_count(db, user_id)

    result = await db.execute(
        select(Notification)
        .where(*filters)
        .order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )

    notifications = result.scalars().all()
    items = []

    for notification in notifications:
        payload = decrypt_notification_payload(notification)

        items.append(
            NotificationItem(
                id=notification.id,
                notification_type=notification.notification_type,
                title=str(payload.get("title", "Notification")),
                message=str(payload.get("message", "")),
                created_at=notification.created_at,
                sent_at=notification.sent_at,
                read_at=notification.read_at,
                metadata={
                    key: value
                    for key, value in payload.items()
                    if key not in {"title", "message"}
                },
            )
        )

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
        "limit": limit,
        "offset": offset,
    }


async def mark_notification_read(
    db: AsyncSession,
    user_id: str,
    notification_id: str,
):
    result = await db.execute(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.channel == "in_app",
            Notification.status == "sent",
        )
        .with_for_update()
    )

    notification = result.scalar_one_or_none()

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    if notification.read_at is None:
        notification.read_at = utc_now()
        await db.flush()

    return {
        "success": True,
        "notification_id": notification.id,
    }


async def mark_all_notifications_read(db: AsyncSession, user_id: str):
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.channel == "in_app",
            Notification.status == "sent",
            Notification.read_at.is_(None),
        )
        .with_for_update()
    )

    notifications = result.scalars().all()
    read_at = utc_now()

    for notification in notifications:
        notification.read_at = read_at

    await db.flush()

    return {
        "success": True,
        "updated_count": len(notifications),
    }
