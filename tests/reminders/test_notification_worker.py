
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers import notification_worker


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def make_notification(
    notification_type="medication_reminder",
    medication_log_id="dose-1",
):
    return SimpleNamespace(
        id="notification-1",
        user_id="user-1",
        notification_type=notification_type,
        medication_log_id=medication_log_id,
        status="sending",
        updated_at=None,
    )


def make_db(notification, dose=None):
    db = MagicMock()
    db.get = AsyncMock(return_value=notification)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = dose
    db.execute = AsyncMock(return_value=result)

    return db


def setup_worker(monkeypatch, db, notification):
    monkeypatch.setattr(
        notification_worker,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(db),
    )

    monkeypatch.setattr(
        notification_worker,
        "claim_due_notifications",
        AsyncMock(return_value=[notification]),
    )

    monkeypatch.setattr(
        notification_worker,
        "decrypt_notification_payload",
        MagicMock(return_value={"title": "Test reminder"}),
    )

    monkeypatch.setattr(
        notification_worker,
        "mark_notification_sent",
        AsyncMock(
            side_effect=lambda session, item: setattr(
                item, "status", "sent"
            )
        ),
    )

    monkeypatch.setattr(
        notification_worker,
        "mark_notification_failed",
        AsyncMock(),
    )


@pytest.mark.asyncio
async def test_pending_dose_notification_is_sent(monkeypatch):
    notification = make_notification()
    dose = SimpleNamespace(status="pending")
    db = make_db(notification, dose)

    setup_worker(monkeypatch, db, notification)

    result = await notification_worker.process_notification_batch()

    assert result == {
        "claimed": 1,
        "sent": 1,
        "failed": 0,
        "cancelled": 0,
    }

    assert notification.status == "sent"
    notification_worker.mark_notification_sent.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dose_status",
    ["taken", "skipped", "missed"],
)
async def test_non_pending_dose_notification_is_cancelled(
    monkeypatch,
    dose_status,
):
    notification = make_notification()
    dose = SimpleNamespace(status=dose_status)
    db = make_db(notification, dose)

    setup_worker(monkeypatch, db, notification)

    result = await notification_worker.process_notification_batch()

    assert result == {
        "claimed": 1,
        "sent": 0,
        "failed": 0,
        "cancelled": 1,
    }

    assert notification.status == "cancelled"
    notification_worker.mark_notification_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_dose_notification_is_cancelled(monkeypatch):
    notification = make_notification()
    db = make_db(notification, dose=None)

    setup_worker(monkeypatch, db, notification)

    result = await notification_worker.process_notification_batch()

    assert result["cancelled"] == 1
    assert result["sent"] == 0
    assert notification.status == "cancelled"


@pytest.mark.asyncio
async def test_medication_reminder_without_dose_is_cancelled(monkeypatch):
    notification = make_notification(
        notification_type="medication_reminder",
        medication_log_id=None,
    )
    db = make_db(notification)

    setup_worker(monkeypatch, db, notification)

    result = await notification_worker.process_notification_batch()

    assert result["cancelled"] == 1
    assert result["sent"] == 0
    assert notification.status == "cancelled"

    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_notification_without_dose_is_sent(monkeypatch):
    notification = make_notification(
        notification_type="general",
        medication_log_id=None,
    )
    db = make_db(notification)

    setup_worker(monkeypatch, db, notification)

    result = await notification_worker.process_notification_batch()

    assert result == {
        "claimed": 1,
        "sent": 1,
        "failed": 0,
        "cancelled": 0,
    }

    assert notification.status == "sent"
    db.execute.assert_not_awaited()
