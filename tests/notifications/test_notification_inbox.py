
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models.user import User
from app.models.notification import Notification
from app.modules.notifications.service import (
    encrypt_notification_payload,
)
from app.modules.notifications.inbox_service import (
    get_unread_count,
    list_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)


@pytest_asyncio.fixture
async def inbox_db():
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
                    full_name="MEDI Inbox Test",
                    email=f"inbox-test-{user_id}@example.com",
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


async def create_notification(
    db,
    user,
    status="sent",
    channel="in_app",
):
    notification_id = str(uuid.uuid4())

    payload = {
        "title": "Medication reminder",
        "message": "Time to take your medicine",
        "dose_log_id": str(uuid.uuid4()),
        "action": "medication_reminder",
    }

    notification = Notification(
        id=notification_id,
        user_id=user.id,
        channel=channel,
        notification_type="medication_reminder",
        encrypted_payload=encrypt_notification_payload(
            user.id,
            notification_id,
            payload,
        ),
        status=status,
        idempotency_key=f"inbox-test:{notification_id}",
        scheduled_at=datetime.now(timezone.utc),
        sent_at=(
            datetime.now(timezone.utc)
            if status == "sent"
            else None
        ),
        attempts=1,
        max_attempts=5,
    )

    db.add(notification)
    await db.flush()

    return notification


@pytest.mark.asyncio
async def test_list_notifications_decrypts_own_notifications(
    inbox_db,
):
    db, user = inbox_db

    notification = await create_notification(db, user)

    result = await list_notifications(
        db,
        user.id,
        limit=20,
        offset=0,
    )

    assert result["total"] == 1
    assert result["unread_count"] == 1
    assert len(result["items"]) == 1

    item = result["items"][0]

    assert item.id == notification.id
    assert item.title == "Medication reminder"
    assert item.message == "Time to take your medicine"
    assert item.read_at is None
    assert "dose_log_id" in item.metadata


@pytest.mark.asyncio
async def test_unread_count_ignores_read_and_unsent_notifications(
    inbox_db,
):
    db, user = inbox_db

    unread = await create_notification(db, user)
    read = await create_notification(db, user)
    await create_notification(db, user, status="pending")

    read.read_at = datetime.now(timezone.utc)

    count = await get_unread_count(db, user.id)

    assert count == 1
    assert unread.read_at is None


@pytest.mark.asyncio
async def test_mark_notification_read(inbox_db):
    db, user = inbox_db

    notification = await create_notification(db, user)

    result = await mark_notification_read(
        db,
        user.id,
        notification.id,
    )

    assert result["success"] is True
    assert result["notification_id"] == notification.id
    assert notification.read_at is not None

    first_read_at = notification.read_at

    # Repeated read request should be idempotent.
    await mark_notification_read(
        db,
        user.id,
        notification.id,
    )

    assert notification.read_at == first_read_at


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_notification(
    inbox_db,
):
    db, user = inbox_db

    other_user_id = str(uuid.uuid4())

    other_user = User(
        id=other_user_id,
        full_name="Another Test User",
        email=f"another-inbox-{other_user_id}@example.com",
        password_hash="test-only-not-a-real-password",
        is_active=True,
        is_verified=True,
    )

    db.add(other_user)
    await db.flush()

    notification = await create_notification(db, other_user)

    with pytest.raises(HTTPException) as error:
        await mark_notification_read(
            db,
            user.id,
            notification.id,
        )

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_notifications_read(inbox_db):
    db, user = inbox_db

    first = await create_notification(db, user)
    second = await create_notification(db, user)
    await create_notification(db, user, status="pending")

    result = await mark_all_notifications_read(
        db,
        user.id,
    )

    assert result["success"] is True
    assert result["updated_count"] == 2

    assert first.read_at is not None
    assert second.read_at is not None

    remaining = await get_unread_count(db, user.id)

    assert remaining == 0


@pytest.mark.asyncio
async def test_notification_list_pagination(inbox_db):
    db, user = inbox_db

    for _ in range(3):
        await create_notification(db, user)

    first_page = await list_notifications(
        db,
        user.id,
        limit=2,
        offset=0,
    )

    second_page = await list_notifications(
        db,
        user.id,
        limit=2,
        offset=2,
    )

    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
