
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.medication import MedicationLog
from app.models.notification import Notification
from app.modules.notifications.service import (
    claim_due_notifications,
    decrypt_notification_payload,
    mark_notification_failed,
    mark_notification_sent,
)

logger = logging.getLogger("medi.notification_worker")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def process_notification_batch(
    batch_size: int = 100,
) -> dict[str, int]:
    """
    Claim and process due in-app notifications.

    Medication reminders are cancelled if their associated dose
    is no longer pending or no longer exists.

    No email or push notifications are sent.
    """

    async with AsyncSessionLocal() as db:
        notifications = await claim_due_notifications(
            db,
            limit=batch_size,
        )
        claimed_ids = [item.id for item in notifications]
        await db.commit()

    results = {
        "claimed": len(claimed_ids),
        "sent": 0,
        "failed": 0,
        "cancelled": 0,
    }

    for notification_id in claimed_ids:
        async with AsyncSessionLocal() as db:
            try:
                notification = await db.get(
                    Notification,
                    notification_id,
                    with_for_update=True,
                )

                if notification is None:
                    continue

                if notification.status != "sending":
                    continue

                # Validate notifications linked to medication doses.
                if notification.medication_log_id is not None:
                    dose_result = await db.execute(
                        select(MedicationLog)
                        .where(
                            MedicationLog.id
                            == notification.medication_log_id
                        )
                        .with_for_update()
                    )

                    dose = dose_result.scalar_one_or_none()

                    if dose is None or dose.status != "pending":
                        notification.status = "cancelled"
                        notification.updated_at = utc_now()

                        await db.commit()
                        results["cancelled"] += 1
                        continue

                elif notification.notification_type == "medication_reminder":
                    # A medication reminder without a dose record
                    # is invalid and must not be delivered.
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()

                    await db.commit()
                    results["cancelled"] += 1
                    continue

                # Verify encrypted payload integrity before delivery.
                decrypt_notification_payload(notification)

                await mark_notification_sent(
                    db,
                    notification,
                )

                await db.commit()
                results["sent"] += 1

            except Exception as exc:
                await db.rollback()

                logger.exception(
                    "Notification delivery failed: %s",
                    notification_id,
                )

                async with AsyncSessionLocal() as retry_db:
                    notification = await retry_db.get(
                        Notification,
                        notification_id,
                        with_for_update=True,
                    )

                    if (
                        notification is not None
                        and notification.status == "sending"
                    ):
                        await mark_notification_failed(
                            retry_db,
                            notification,
                            str(exc),
                        )

                        await retry_db.commit()
                        results["failed"] += 1

    return results


async def run_notification_cycle() -> dict[str, int]:
    totals = {
        "claimed": 0,
        "sent": 0,
        "failed": 0,
        "cancelled": 0,
    }

    while True:
        result = await process_notification_batch()

        for key, value in result.items():
            totals[key] += value

        if result["claimed"] == 0:
            break

    return totals


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("MEDI notification worker started")

    try:
        while True:
            try:
                result = await run_notification_cycle()

                if result["claimed"]:
                    logger.info(
                        "Notification cycle: %s",
                        result,
                    )

            except Exception:
                logger.exception(
                    "Notification cycle failed"
                )

            await asyncio.sleep(5)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MEDI notification worker stopped")
