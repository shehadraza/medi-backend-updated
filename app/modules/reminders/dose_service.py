
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medication import (
    Medication,
    MedicationSchedule,
    MedicationLog,
)

from app.modules.reminders.service import decrypt_schedule


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def parse_schedule_date(value) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(value)


def parse_reminder_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
        return parsed.replace(tzinfo=None)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Invalid reminder time in stored schedule.",
        )


async def generate_due_doses(
    db: AsyncSession,
    user_id: str,
    horizon_minutes: int = 24 * 60,
    lookback_minutes: int = 24 * 60,
) -> int:
    """
    Generate pending dose logs for a bounded past and future window.

    Repeated executions are safe because the database unique constraint
    prevents duplicate logs for the same schedule and scheduled time.

    A separate missed-dose processor changes overdue pending logs
    to missed after the configured grace period.
    """

    if not 1 <= horizon_minutes <= 7 * 24 * 60:
        raise HTTPException(
            status_code=422,
            detail="Invalid dose generation horizon.",
        )

    if not 1 <= lookback_minutes <= 7 * 24 * 60:
        raise HTTPException(
            status_code=422,
            detail="Invalid dose generation lookback.",
        )

    now = utc_now()
    window_start = now - timedelta(minutes=lookback_minutes)
    window_end = now + timedelta(minutes=horizon_minutes)

    result = await db.execute(
        select(MedicationSchedule, Medication)
        .join(
            Medication,
            Medication.id == MedicationSchedule.medication_id,
        )
        .where(
            MedicationSchedule.user_id == user_id,
            MedicationSchedule.is_active.is_(True),
            Medication.status == "active",
        )
    )

    rows = result.all()
    created_count = 0

    for schedule, medication in rows:
        data = decrypt_schedule(schedule)

        if not data.get("reminder_enabled", True):
            continue

        try:
            tz = ZoneInfo(data["timezone_name"])
        except (KeyError, ZoneInfoNotFoundError):
            raise HTTPException(
                status_code=422,
                detail="Invalid timezone in medication schedule.",
            )

        reminder_times = data.get("reminder_times", [])

        if not reminder_times:
            continue

        recurrence = data.get("recurrence")

        if recurrence not in {"daily", "weekly"}:
            raise HTTPException(
                status_code=422,
                detail="Invalid recurrence in medication schedule.",
            )

        weekdays = data.get("weekdays", [])

        if recurrence == "weekly" and not weekdays:
            raise HTTPException(
                status_code=422,
                detail="Weekly schedule has no selected weekdays.",
            )

        schedule_start = parse_schedule_date(
            data.get("start_date")
        )
        schedule_end = parse_schedule_date(
            data.get("end_date")
        )

        if (
            schedule_start
            and schedule_end
            and schedule_end < schedule_start
        ):
            raise HTTPException(
                status_code=422,
                detail="Invalid schedule date range.",
            )

        local_window_start = window_start.astimezone(tz)
        local_window_end = window_end.astimezone(tz)

        first_date = local_window_start.date()
        last_date = local_window_end.date()

        if schedule_start:
            first_date = max(first_date, schedule_start)

        if schedule_end:
            last_date = min(last_date, schedule_end)

        medication_start = (
            normalize_datetime(medication.start_date)
            if medication.start_date
            else None
        )

        medication_end = (
            normalize_datetime(medication.end_date)
            if medication.end_date
            else None
        )

        if first_date > last_date:
            continue

        current_date = first_date

        while current_date <= last_date:
            weekday = current_date.weekday()

            should_run = (
                recurrence == "daily"
                or weekday in weekdays
            )

            if should_run:
                for time_value in reminder_times:
                    parsed_time = parse_reminder_time(time_value)

                    local_dose = datetime.combine(
                        current_date,
                        parsed_time,
                        tzinfo=tz,
                    )

                    scheduled_at = local_dose.astimezone(
                        timezone.utc
                    )

                    if not (
                        window_start <= scheduled_at <= window_end
                    ):
                        continue

                    if (
                        medication_start
                        and scheduled_at < medication_start
                    ):
                        continue

                    if (
                        medication_end
                        and scheduled_at > medication_end
                    ):
                        continue

                    statement = (
                        insert(MedicationLog)
                        .values(
                            id=str(uuid.uuid4()),
                            medication_id=medication.id,
                            schedule_id=schedule.id,
                            user_id=user_id,
                            scheduled_at=scheduled_at,
                            taken_at=None,
                            status="pending",
                        )
                        .on_conflict_do_nothing(
                            constraint="uq_medication_log_schedule_dose"
                        )
                    )

                    insert_result = await db.execute(statement)

                    if insert_result.rowcount == 1:
                        created_count += 1

            current_date += timedelta(days=1)

    await db.flush()
    return created_count


async def mark_dose(
    db: AsyncSession,
    user_id: str,
    log_id: str,
    status: str,
) -> MedicationLog:
    if status not in {"taken", "skipped"}:
        raise HTTPException(
            status_code=422,
            detail="Dose status must be taken or skipped.",
        )

    result = await db.execute(
        select(MedicationLog)
        .where(
            MedicationLog.id == log_id,
            MedicationLog.user_id == user_id,
        )
        .with_for_update()
    )

    log = result.scalar_one_or_none()

    if log is None:
        raise HTTPException(
            status_code=404,
            detail="Dose record not found.",
        )

    if log.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="This dose has already been processed.",
        )

    log.status = status
    log.taken_at = utc_now() if status == "taken" else None

    await db.flush()
    return log


async def mark_missed_doses(
    db: AsyncSession,
    user_id: str,
    grace_minutes: int = 120,
) -> int:
    if not 1 <= grace_minutes <= 24 * 60:
        raise HTTPException(
            status_code=422,
            detail="Invalid missed-dose grace period.",
        )

    cutoff = utc_now() - timedelta(minutes=grace_minutes)

    result = await db.execute(
        select(MedicationLog)
        .where(
            MedicationLog.user_id == user_id,
            MedicationLog.status == "pending",
            MedicationLog.scheduled_at <= cutoff,
        )
        .with_for_update()
    )

    logs = result.scalars().all()

    for log in logs:
        log.status = "missed"

    await db.flush()
    return len(logs)


async def get_adherence(
    db: AsyncSession,
    user_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    if start and end:
        start = normalize_datetime(start)
        end = normalize_datetime(end)

        if end < start:
            raise HTTPException(
                status_code=422,
                detail="End date cannot be before start date.",
            )

    query = select(MedicationLog).where(
        MedicationLog.user_id == user_id
    )

    if start:
        query = query.where(
            MedicationLog.scheduled_at >= start
        )

    if end:
        query = query.where(
            MedicationLog.scheduled_at <= end
        )

    result = await db.execute(query)
    logs = result.scalars().all()

    total = len(logs)

    taken = sum(log.status == "taken" for log in logs)
    skipped = sum(log.status == "skipped" for log in logs)
    missed = sum(log.status == "missed" for log in logs)
    pending = sum(log.status == "pending" for log in logs)

    completed_or_missed = taken + skipped + missed

    percentage = (
        round(taken / completed_or_missed * 100, 2)
        if completed_or_missed
        else 0.0
    )

    return {
        "total_doses": total,
        "taken": taken,
        "skipped": skipped,
        "missed": missed,
        "pending": pending,
        "adherence_percentage": percentage,
    }
