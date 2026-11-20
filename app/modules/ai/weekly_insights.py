"""Deterministic weekly medication insights from explicitly recorded dose logs."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_profile import HealthProfile
from app.models.medication import Medication, MedicationLog


UTC = timezone.utc
WINDOW_DAYS = 7


def _weekly_period(now: datetime, timezone_name: str) -> tuple[ZoneInfo, datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        user_tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A valid IANA timezone is required.",
        ) from exc

    local_today = now.astimezone(UTC).astimezone(user_tz).date()
    local_start = datetime.combine(
        local_today - timedelta(days=WINDOW_DAYS), time.min, tzinfo=user_tz,
    )
    local_end = datetime.combine(local_today, time.min, tzinfo=user_tz)
    return user_tz, local_start.astimezone(UTC), local_end.astimezone(UTC)


def _aggregate_event_groups(rows) -> dict:
    """Aggregate SQL-deduplicated event groups; conflicts are never guessed."""
    counts = {
        "scheduled_doses": 0,
        "taken_doses": 0,
        "missed_doses": 0,
        "skipped_doses": 0,
        "pending_doses": 0,
        "cancelled_doses": 0,
        "unclassified_doses": 0,
        "duplicate_records_ignored": 0,
    }

    for row in rows:
        record_count = int(row.record_count or 0)
        if record_count <= 0:
            continue
        counts["duplicate_records_ignored"] += max(0, record_count - 1)

        first_status = (row.first_status or "").strip().casefold()
        last_status = (row.last_status or "").strip().casefold()
        if first_status != last_status:
            counts["scheduled_doses"] += 1
            counts["unclassified_doses"] += 1
            continue

        if first_status in {"cancelled", "canceled"}:
            counts["cancelled_doses"] += 1
            continue

        counts["scheduled_doses"] += 1
        if first_status == "taken":
            counts["taken_doses"] += 1
        elif first_status == "missed":
            counts["missed_doses"] += 1
        elif first_status == "skipped":
            counts["skipped_doses"] += 1
        elif first_status == "pending":
            counts["pending_doses"] += 1
        else:
            counts["unclassified_doses"] += 1

    denominator = (
        counts["taken_doses"]
        + counts["missed_doses"]
        + counts["skipped_doses"]
    )
    counts["adherence_denominator"] = denominator
    counts["adherence_percentage"] = (
        round(counts["taken_doses"] / denominator * 100, 2)
        if denominator else None
    )
    return counts


async def get_weekly_medication_insight(
    db: AsyncSession,
    user_id: str,
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> dict:
    """Return the previous seven complete local calendar days of owned dose logs.

    This is an authenticated, user-requested insight. It requires the existing
    interactive personalization consent, not proactive-analysis consent.
    """
    now = now or datetime.now(UTC)
    user_tz, start_utc, end_utc = _weekly_period(now, timezone_name)

    try:
        consent_result = await db.execute(
            select(HealthProfile.ai_personalization_consent)
            .where(HealthProfile.user_id == user_id)
            .with_for_update()
        )
        consent = consent_result.scalar_one_or_none()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weekly medication insight is temporarily unavailable.",
        ) from exc

    if consent is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Interactive personalization consent is required for this insight.",
        )

    event_key = func.coalesce(MedicationLog.schedule_id, MedicationLog.medication_id)
    statement = (
        select(
            event_key.label("event_key"),
            MedicationLog.scheduled_at.label("scheduled_at"),
            func.count().label("record_count"),
            func.min(MedicationLog.status).label("first_status"),
            func.max(MedicationLog.status).label("last_status"),
        )
        .where(
            MedicationLog.user_id == user_id,
            Medication.user_id == user_id,
            MedicationLog.scheduled_at >= start_utc,
            MedicationLog.scheduled_at < end_utc,
        )
        .join(Medication, Medication.id == MedicationLog.medication_id)
        .group_by(event_key, MedicationLog.scheduled_at)
    )
    try:
        result = await db.execute(statement)
        counts = _aggregate_event_groups(result.all())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weekly medication insight is temporarily unavailable.",
        ) from exc

    local_start = start_utc.astimezone(user_tz)
    local_end = end_utc.astimezone(user_tz)
    observations = [
        "dose_log_records_only",
        "future_logs_are_outside_the_completed_week",
        "unrecorded_doses_not_inferred",
    ]
    if counts["pending_doses"]:
        observations.append("pending_doses_are_not_counted_as_missed")
    if counts["cancelled_doses"]:
        observations.append("cancelled_doses_are_excluded_from_adherence")
    if counts["duplicate_records_ignored"]:
        observations.append("duplicate_records_were_collapsed_by_schedule_and_time")
    if counts["unclassified_doses"]:
        observations.append("unclassified_or_conflicting_records_are_excluded_from_adherence")
    if counts["adherence_denominator"] == 0:
        observations.append("adherence_is_unavailable_without_completed_classified_records")

    return {
        "timezone_name": user_tz.key,
        "period_start_local": local_start,
        "period_end_local_exclusive": local_end,
        "period_start_utc": start_utc,
        "period_end_utc_exclusive": end_utc,
        "recorded_facts": counts,
        "observations": observations,
    }
