
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.health_profile import HealthProfile
from app.modules.health.service import (
    get_health_profile,
    save_health_profile,
)


async def get_onboarding_state(
    db: AsyncSession,
    user_id: str,
) -> dict[str, Any]:
    result = await db.execute(
        select(HealthProfile).where(
            HealthProfile.user_id == user_id
        )
    )
    profile_record = result.scalar_one_or_none()

    profile_data = await get_health_profile(db, user_id)

    return {
        "profile": profile_data,
        "onboarding_completed": (
            profile_record.onboarding_completed_at is not None
            if profile_record else False
        ),
        "ai_personalization_consent": (
            profile_record.ai_personalization_consent
            if profile_record else False
        ),
        "proactive_health_analysis_consent": (
            profile_record.proactive_health_analysis_consent
            if profile_record else False
        ),
        "proactive_wellness_notifications_consent": (
            profile_record.proactive_wellness_notifications_consent
            if profile_record else False
        ),
    }


async def get_consent_status(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """Read only consent columns; never decrypt or select profile content."""
    result = await db.execute(
        select(
            HealthProfile.ai_personalization_consent,
            HealthProfile.ai_personalization_consent_at,
            HealthProfile.proactive_health_analysis_consent,
            HealthProfile.proactive_health_analysis_consent_at,
            HealthProfile.proactive_wellness_notifications_consent,
            HealthProfile.proactive_wellness_notifications_consent_at,
        ).where(HealthProfile.user_id == user_id)
    )
    row = result.one_or_none()
    if row is None:
        return {
            "ai_personalization_consent": False,
            "ai_personalization_consent_at": None,
            "proactive_health_analysis_consent": False,
            "proactive_health_analysis_consent_at": None,
            "proactive_wellness_notifications_consent": False,
            "proactive_wellness_notifications_consent_at": None,
        }
    return {
        "ai_personalization_consent": row[0] is True,
        "ai_personalization_consent_at": row[1],
        "proactive_health_analysis_consent": row[2] is True,
        "proactive_health_analysis_consent_at": row[3],
        "proactive_wellness_notifications_consent": row[4] is True,
        "proactive_wellness_notifications_consent_at": row[5],
    }


async def update_onboarding_profile(
    db: AsyncSession,
    user_id: str,
    profile_data: dict[str, Any],
) -> HealthProfile:
    existing_data = await get_health_profile(db, user_id)

    merged_data = existing_data or {}
    merged_data.update(profile_data)

    return await save_health_profile(
        db=db,
        user_id=user_id,
        data=merged_data,
    )


async def update_ai_personalization_consent(
    db: AsyncSession,
    user_id: str,
    enabled: bool,
) -> HealthProfile:
    result = await db.execute(
        select(HealthProfile).where(
            HealthProfile.user_id == user_id
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = await save_health_profile(
            db=db,
            user_id=user_id,
            data={},
        )

    profile.ai_personalization_consent = enabled

    profile.ai_personalization_consent_at = (
        datetime.now(timezone.utc) if enabled else None
    )

    await db.flush()

    return profile


async def update_proactive_consent(
    db: AsyncSession,
    user_id: str,
    *,
    scope: str,
    enabled: bool,
) -> HealthProfile:
    """Update one proactive scope without touching encrypted profile data."""
    fields = {
        "health_analysis": (
            "proactive_health_analysis_consent",
            "proactive_health_analysis_consent_at",
        ),
        "wellness_notifications": (
            "proactive_wellness_notifications_consent",
            "proactive_wellness_notifications_consent_at",
        ),
    }
    if scope not in fields:
        raise ValueError("Unknown proactive consent scope.")

    consent_field, timestamp_field = fields[scope]
    result = await db.execute(
        select(HealthProfile).where(HealthProfile.user_id == user_id).with_for_update()
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = await save_health_profile(db=db, user_id=user_id, data={})

    current = getattr(profile, consent_field) is True
    if current != enabled:
        setattr(profile, consent_field, enabled)
        setattr(profile, timestamp_field, datetime.now(timezone.utc))
    await db.flush()
    return profile


async def complete_onboarding(
    db: AsyncSession,
    user_id: str,
) -> HealthProfile:
    result = await db.execute(
        select(HealthProfile).where(
            HealthProfile.user_id == user_id
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        raise ValueError("Health profile must exist before completing onboarding.")

    profile.onboarding_completed_at = datetime.now(timezone.utc)

    await db.flush()

    return profile
