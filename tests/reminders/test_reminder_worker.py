
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers import reminder_worker


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def make_query_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_get_users_requiring_reminder_processing():
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            make_query_result(["user-1", "user-2"]),
            make_query_result(["user-2", "user-3"]),
        ]
    )

    users = await reminder_worker.get_users_requiring_reminder_processing(db)

    assert users == {"user-1", "user-2", "user-3"}


@pytest.mark.asyncio
async def test_process_user_reminders_commits_successfully(monkeypatch):
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    monkeypatch.setattr(
        reminder_worker,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(db),
    )
    monkeypatch.setattr(
        reminder_worker,
        "generate_due_doses",
        AsyncMock(return_value=3),
    )
    monkeypatch.setattr(
        reminder_worker,
        "mark_missed_doses",
        AsyncMock(return_value=2),
    )
    monkeypatch.setattr(
        reminder_worker,
        "enqueue_dose_notifications",
        AsyncMock(return_value=4),
    )
    monkeypatch.setattr(
        reminder_worker,
        "enqueue_missed_dose_notice",
        AsyncMock(return_value=1),
    )

    result = await reminder_worker.process_user_reminders("user-1")

    assert result == {
        "generated": 3,
        "missed": 2,
        "notifications_created": 5,
    }

    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_user_reminders_rolls_back_on_error(monkeypatch):
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    monkeypatch.setattr(
        reminder_worker,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(db),
    )
    monkeypatch.setattr(
        reminder_worker,
        "generate_due_doses",
        AsyncMock(side_effect=RuntimeError("Database failure")),
    )

    with pytest.raises(RuntimeError, match="Database failure"):
        await reminder_worker.process_user_reminders("user-1")

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_reminder_cycle_continues_after_user_failure(monkeypatch):
    monkeypatch.setattr(
        reminder_worker,
        "get_users_requiring_reminder_processing",
        AsyncMock(return_value={"bad-user", "good-user"}),
    )

    async def fake_process(user_id):
        if user_id == "bad-user":
            raise RuntimeError("User processing failed")

        return {
            "generated": 2,
            "missed": 1,
            "notifications_created": 3,
        }

    monkeypatch.setattr(
        reminder_worker,
        "process_user_reminders",
        fake_process,
    )

    db = MagicMock()
    monkeypatch.setattr(
        reminder_worker,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(db),
    )

    result = await reminder_worker.run_reminder_cycle()

    assert result == {
        "users_processed": 1,
        "generated": 2,
        "missed": 1,
        "notifications_created": 3,
        "failed_users": 1,
    }


@pytest.mark.asyncio
async def test_run_reminder_cycle_handles_no_users(monkeypatch):
    monkeypatch.setattr(
        reminder_worker,
        "get_users_requiring_reminder_processing",
        AsyncMock(return_value=set()),
    )

    db = MagicMock()
    monkeypatch.setattr(
        reminder_worker,
        "AsyncSessionLocal",
        lambda: FakeSessionContext(db),
    )

    result = await reminder_worker.run_reminder_cycle()

    assert result == {
        "users_processed": 0,
        "generated": 0,
        "missed": 0,
        "notifications_created": 0,
        "failed_users": 0,
    }
