
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from app.modules.notifications.service import (
    enqueue_dose_notifications,
    enqueue_missed_dose_notice,
)

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.medication import MedicationLog, MedicationSchedule
from app.modules.reminders.dose_service import (
    generate_due_doses,
    mark_missed_doses,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("medi.reminder_worker")


async def get_users_requiring_reminder_processing(db) -> set[str]:
    """Find users who have active schedules or pending dose logs."""

    active_result = await db.execute(
        select(MedicationSchedule.user_id)
        .where(MedicationSchedule.is_active.is_(True))
        .distinct()
    )

    pending_result = await db.execute(
        select(MedicationLog.user_id)
        .where(MedicationLog.status == "pending")
        .distinct()
    )

    user_ids = set(active_result.scalars().all())
    user_ids.update(pending_result.scalars().all())

    return user_ids


async def process_user_reminders(user_id: str) -> dict[str, int]:
    """Generate due doses and mark overdue doses as missed."""

    async with AsyncSessionLocal() as db:
        try:
            generated = await generate_due_doses(
                db=db,
                user_id=user_id,
                horizon_minutes=settings.REMINDER_GENERATION_HORIZON_MINUTES,
                lookback_minutes=settings.REMINDER_GENERATION_LOOKBACK_MINUTES,
            )

            missed = await mark_missed_doses(
                db=db,
                user_id=user_id,
                grace_minutes=settings.REMINDER_DOSE_GRACE_MINUTES,
            )

            notifications_created = await enqueue_dose_notifications(
                db=db,
                user_id=user_id,
            )
            notifications_created += await enqueue_missed_dose_notice(
                db=db, user_id=user_id, missed_count=missed,
            )

            await db.commit()

            return {
                "generated": generated,
                "missed": missed,
                "notifications_created": notifications_created,
            }

        except Exception:
            await db.rollback()
            logger.exception(
                "Reminder processing failed for user %s",
                user_id,
            )
            raise


async def run_reminder_cycle() -> dict[str, int]:
    """Run one reminder-processing cycle for all relevant users."""

    totals = {
        "users_processed": 0,
        "generated": 0,
        "missed": 0,
        "failed_users": 0,
        "notifications_created": 0,
    }

    async with AsyncSessionLocal() as db:
        user_ids = await get_users_requiring_reminder_processing(db)

    if not user_ids:
        logger.info("No active reminders or pending doses found.")
        return totals

    logger.info("Processing reminders for %s users.", len(user_ids))

    for user_id in user_ids:
        try:
            result = await process_user_reminders(user_id)

            totals["users_processed"] += 1
            totals["generated"] += result["generated"]
            totals["missed"] += result["missed"]
            totals["notifications_created"] += result["notifications_created"]

        except Exception:
            totals["failed_users"] += 1
            continue

    logger.info(
        "Reminder cycle completed: users=%s, generated=%s, missed=%s, failed=%s",
        totals["users_processed"],
        totals["generated"],
        totals["missed"],
        totals["failed_users"],
    )

    return totals


async def main() -> None:
    interval = settings.REMINDER_WORKER_INTERVAL_SECONDS

    if interval < 5:
        raise ValueError(
            "REMINDER_WORKER_INTERVAL_SECONDS must be at least 5."
        )

    if settings.REMINDER_DOSE_GRACE_MINUTES < 1:
        raise ValueError(
            "REMINDER_DOSE_GRACE_MINUTES must be at least 1."
        )

    if settings.REMINDER_GENERATION_HORIZON_MINUTES < 1:
        raise ValueError(
            "REMINDER_GENERATION_HORIZON_MINUTES must be at least 1."
        )

    if settings.REMINDER_GENERATION_LOOKBACK_MINUTES < 1:
        raise ValueError(
            "REMINDER_GENERATION_LOOKBACK_MINUTES must be at least 1."
        )

    logger.info("MEDI Reminder Worker started.")
    logger.info("Worker interval: %s seconds", interval)
    logger.info(
        "Dose grace period: %s minutes",
        settings.REMINDER_DOSE_GRACE_MINUTES,
    )

    try:
        while True:
            try:
                await run_reminder_cycle()
            except Exception:
                logger.exception("Reminder cycle failed unexpectedly.")

            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info("Reminder Worker shutdown requested.")
        raise

    finally:
        await engine.dispose()
        logger.info("Reminder Worker database connection closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Reminder Worker stopped by user.")
