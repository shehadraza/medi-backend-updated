"""Consent-gated, minimal access to the authenticated user's health records."""

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data
from app.models.health_profile import HealthProfile
from app.models.medication import (
    Medication,
    MedicationSchedule,
    Prescription,
    PrescriptionItem,
)
from app.modules.health.service import get_health_profile
from app.modules.medicines.prescription_sync import (
    item_associated_data,
    medication_associated_data,
)
from app.modules.reminders.dose_service import get_adherence
from app.modules.reminders.service import decrypt_schedule
from app.modules.health.checkin_service import list_checkins


MEDICATION_QUERY = re.compile(
    r"\b(medicine|medication|drug|prescription|dose|dosage|tablet|capsule|take|"
    r"schedule|reminder|adherence|missed|taken|interaction|allerg|side effect)\b|"
    r"(ওষুধ|ঔষধ|প্রেসক্রিপশন|মাত্রা|ডোজ|অ্যালার্জি|খেয়েছি|খাইনি|মিসড)",
    re.IGNORECASE,
)
ACTIVITY_QUERY = re.compile(
    r"\b(adherence|missed|taken|dose|schedule|reminder)\b|"
    r"(খেয়েছি|খাইনি|মিসড|রিমাইন্ডার|সময়সূচি)",
    re.IGNORECASE,
)
LIFESTYLE_QUERY = re.compile(
    r"\b(sleep|water|exercise|activity|diet|food|stress|lifestyle|weight|goal|screen\s*time)\b|"
    r"(ঘুম|পানি|ব্যায়াম|খাদ্য|খাবার|চাপ|জীবনযাপন)",
    re.IGNORECASE,
)
HEALTH_CHECKIN_QUERY = re.compile(
    r"\b(check.?in|health progress|health trend|weekly health|daily health|"
    r"symptom|wellbeing|well-being|energy level|sleep|water intake|hydration|"
    r"exercise|physical activity|screen time|eating habit|junk food|stress)\b|"
    r"(দৈনিক স্বাস্থ্য|স্বাস্থ্য অগ্রগতি|স্বাস্থ্য কেমন|লক্ষণ|উপসর্গ|শক্তির মাত্রা|"
    r"ঘুম|পানি|ব্যায়াম|শারীরিক কার্যকলাপ|স্ক্রিন টাইম|খাদ্যাভ্যাস|জাঙ্ক ফুড|মানসিক চাপ)|"
    r"\b(amar|ami|amarer)\b.{0,35}\b(ghum|pani|khabar|shorir|oshustho|"
    r"matha betha|energy|stress|exercise)\b",
    re.IGNORECASE,
)
CHECKIN_DATA_FIELDS = (
    "sleep_duration_hours", "sleep_quality", "water_intake_liters",
    "physical_activity", "physical_activity_minutes", "screen_time_hours",
    "eating_habits", "junk_food_portions", "wellbeing_level", "energy_level",
    "symptoms", "notes",
)


def _bounded_checkin_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only known, size-bounded user-reported check-in fields."""
    bounded: dict[str, Any] = {}
    for key in CHECKIN_DATA_FIELDS:
        value = data.get(key)
        if isinstance(value, str):
            bounded[key] = value.replace("\x00", "")[:500]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            bounded[key] = value
        elif key == "symptoms" and isinstance(value, list):
            bounded[key] = [
                item.replace("\x00", "")[:200]
                for item in value[:10]
                if isinstance(item, str) and item.strip()
            ]
    return bounded


async def _recent_health_checkins(
    db: AsyncSession,
    user_id: str,
    *,
    days: int = 14,
    limit: int = 7,
) -> list[dict[str, Any]]:
    """Read only the authenticated user's recent, encrypted daily check-ins."""
    today = datetime.now(timezone.utc).date()
    records = await list_checkins(
        db,
        user_id,
        start_date=today - timedelta(days=days - 1),
        # Include the user's current local date when it is ahead of UTC.
        end_date=today + timedelta(days=1),
        limit=limit,
        offset=0,
    )
    result = []
    for record in records:
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        bounded = _bounded_checkin_data(data)
        if bounded:
            result.append({
                "local_date": record["local_date"].isoformat(),
                "timezone_name": record.get("timezone_name"),
                "data_provenance": "user_reported_daily_checkin_not_clinically_verified",
                "reported_data": bounded,
            })
    return result


def _select_profile_fields(profile: dict[str, Any], query: str) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key in ("health_conditions", "allergies"):
        value = profile.get(key)
        if isinstance(value, list) and value:
            selected[key] = [str(item)[:200] for item in value[:30] if item]

    if LIFESTYLE_QUERY.search(query):
        for key in (
            "age_years", "sleep_hours", "sleep_quality", "water_intake_liters",
            "activity_level", "exercise_days_per_week", "screen_time_hours", "diet_type",
            "junk_food_frequency", "stress_level", "health_goals",
        ):
            value = profile.get(key)
            if value not in (None, [], ""):
                selected[key] = (
                    [str(item)[:200] for item in value[:20] if item]
                    if isinstance(value, list) else value
                )
    return selected


def _bounded_record(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: str(record[key]).replace("\x00", "")[:200]
        for key in keys
        if isinstance(record.get(key), (str, int, float))
    }


async def build_personal_context(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    purpose: Literal["interactive", "proactive_analysis", "wellness_notification"] = "interactive",
) -> dict[str, Any]:
    """Check purpose and data consent before retrieving or decrypting records."""
    purpose_allowed, personal_data_allowed = await get_context_permissions(
        db, user_id, purpose=purpose,
    )
    if not purpose_allowed or not personal_data_allowed:
        result = {"personalization_used": False, "context": {}}
        if purpose != "interactive":
            result.update({
                "purpose_allowed": purpose_allowed,
                "personal_data_used": False,
            })
        return result

    # This is the first operation allowed to retrieve/decrypt personal health data.
    profile_data = await get_health_profile(db, user_id)
    context: dict[str, Any] = {
        "profile": _select_profile_fields(profile_data or {}, query),
    }

    # Daily check-ins are encrypted at rest and are only decrypted after the
    # consent gate above. They are explicitly labeled as user-reported data.
    if HEALTH_CHECKIN_QUERY.search(query) or LIFESTYLE_QUERY.search(query):
        recent_checkins = await _recent_health_checkins(db, user_id)
        if recent_checkins:
            context["recent_user_reported_health_checkins"] = recent_checkins

    if not MEDICATION_QUERY.search(query):
        return {"personalization_used": True, "context": context}

    reported_medicines = profile_data.get("current_medications", []) if profile_data else []
    if isinstance(reported_medicines, list) and reported_medicines:
        context["profile_user_reported_medications"] = [
            str(item)[:200] for item in reported_medicines[:20] if item
        ]

    cabinet_result = await db.execute(
        select(Medication)
        .where(Medication.user_id == user_id, Medication.status == "active")
        .order_by(Medication.updated_at.desc())
        .limit(5)
    )
    cabinet = []
    cabinet_by_id: dict[str, dict[str, Any]] = {}
    for medication in cabinet_result.scalars().all():
        plaintext = decrypt_data(
            medication.encrypted_data,
            associated_data=medication_associated_data(user_id, medication.id),
        )
        try:
            record = json.loads(plaintext)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict):
            # Cabinet entries can be user-entered. Their instructions are not
            # promoted as verified prescription directions.
            bounded = _bounded_record(record, ("medicine_name", "generic_name", "brand_name", "strength", "status"))
            bounded["medication_id"] = medication.id
            cabinet.append(bounded)
            cabinet_by_id[medication.id] = bounded
    if cabinet:
        context["medicine_cabinet_user_reported"] = cabinet

    prescription_result = await db.execute(
        select(PrescriptionItem, Prescription)
        .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
        .where(
            Prescription.user_id == user_id,
            Prescription.confirmed_at.is_not(None),
            PrescriptionItem.verification_status == "verified",
        )
        .order_by(Prescription.confirmed_at.desc())
        .limit(5)
    )
    confirmed = []
    for item, prescription in prescription_result.all():
        plaintext = decrypt_data(
            item.encrypted_data,
            associated_data=item_associated_data(user_id, prescription.id, item.id),
        )
        try:
            record = json.loads(plaintext)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict):
            structured = _bounded_record(
                record,
                (
                    "medicine_name", "generic_name", "brand_name", "strength",
                    "dosage_form", "dose", "frequency", "duration", "timing",
                    "food_instruction",
                ),
            )
            confirmed.append({
                "verification": "user_confirmed_prescription",
                "instructions": structured,
                "confirmed_at": prescription.confirmed_at.isoformat(),
            })
    if confirmed:
        context["confirmed_prescription_instructions"] = confirmed

    # Never inspect OCR payloads here. Any unconfirmed extraction is expressly
    # excluded from the context sent to a model.
    context["unverified_prescription_data_used"] = False

    if ACTIVITY_QUERY.search(query):
        schedule_result = await db.execute(
            select(MedicationSchedule, Medication)
            .join(Medication, Medication.id == MedicationSchedule.medication_id)
            .where(
                MedicationSchedule.user_id == user_id,
                MedicationSchedule.is_active.is_(True),
                Medication.user_id == user_id,
                Medication.status == "active",
            )
            .order_by(MedicationSchedule.next_dose_at.asc().nullslast())
            .limit(5)
        )
        schedules = []
        for schedule, medication in schedule_result.all():
            data = decrypt_schedule(schedule)
            cabinet_entry = cabinet_by_id.get(medication.id, {})
            schedules.append({
                "medicine_name": cabinet_entry.get("medicine_name"),
                "reminder_schedule": {
                    key: data[key]
                    for key in (
                        "reminder_times", "recurrence", "weekdays", "timezone_name",
                        "start_date", "end_date", "reminder_enabled",
                    )
                    if key in data
                },
                "next_dose_at": schedule.next_dose_at.isoformat() if schedule.next_dose_at else None,
            })
        if schedules:
            context["reminder_schedules"] = schedules

        end = datetime.now(timezone.utc)
        adherence = await get_adherence(db, user_id, start=end - timedelta(days=30), end=end)
        context["adherence_last_30_days"] = adherence

    result = {"personalization_used": True, "context": context}
    if purpose != "interactive":
        result.update({"purpose_allowed": True, "personal_data_used": True})
    return result


async def get_context_permissions(
    db: AsyncSession,
    user_id: str,
    *,
    purpose: Literal["interactive", "proactive_analysis", "wellness_notification"],
) -> tuple[bool, bool]:
    """Return (purpose allowed, personal records allowed) using consent-only SQL."""
    if purpose == "interactive":
        result = await db.execute(
            select(HealthProfile.ai_personalization_consent).where(
                HealthProfile.user_id == user_id
            )
        )
        allowed = result.scalar_one_or_none() is True
        return allowed, allowed

    if purpose == "proactive_analysis":
        result = await db.execute(
            select(
                HealthProfile.ai_personalization_consent,
                HealthProfile.proactive_health_analysis_consent,
            ).where(HealthProfile.user_id == user_id)
        )
        consents = result.one_or_none()
        allowed = bool(consents and consents[0] is True and consents[1] is True)
        return allowed, allowed

    if purpose == "wellness_notification":
        result = await db.execute(
            select(
                HealthProfile.ai_personalization_consent,
                HealthProfile.proactive_wellness_notifications_consent,
            ).where(HealthProfile.user_id == user_id)
        )
        consents = result.one_or_none()
        notification_allowed = bool(consents and consents[1] is True)
        personal_data_allowed = bool(consents and consents[0] is True and consents[1] is True)
        return notification_allowed, personal_data_allowed

    raise ValueError("Unknown personal context purpose.")


async def get_personalization_status(db: AsyncSession, user_id: str) -> bool:
    """Minimal consent-only query for the context status endpoint."""
    result = await db.execute(
        select(HealthProfile.ai_personalization_consent).where(
            HealthProfile.user_id == user_id
        )
    )
    return result.scalar_one_or_none() is True
