
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.medication import MedicationSchedule

from app.modules.reminders.schemas import (
    MedicationScheduleCreateRequest,
    MedicationScheduleUpdateRequest,
    MedicationScheduleResponse,
    DoseActionRequest,
    MedicationLogResponse,
    MedicationAdherenceResponse,
)

from app.modules.reminders.service import (
    create_medication_schedule,
    decrypt_schedule,
    update_medication_schedule,
    disable_medication_schedule,
)

from app.modules.reminders.dose_service import (
    generate_due_doses,
    mark_dose,
    mark_missed_doses,
    get_adherence,
)


router = APIRouter(
    prefix="/reminders",
    tags=["Medication Reminders"],
)


def serialize_schedule(
    schedule: MedicationSchedule,
) -> MedicationScheduleResponse:
    data = decrypt_schedule(schedule)

    return MedicationScheduleResponse(
        id=schedule.id,
        medication_id=schedule.medication_id,
        reminder_times=data["reminder_times"],
        recurrence=data["recurrence"],
        weekdays=data["weekdays"],
        timezone_name=data["timezone_name"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        reminder_enabled=data["reminder_enabled"],
        next_dose_at=schedule.next_dose_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


# --------------------------------------------------
# CREATE MEDICATION REMINDER
# --------------------------------------------------

@router.post(
    "",
    response_model=MedicationScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    payload: MedicationScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        schedule = await create_medication_schedule(
            db,
            current_user.id,
            payload,
        )

        await db.commit()
        await db.refresh(schedule)

        return serialize_schedule(schedule)

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# LIST REMINDERS
# --------------------------------------------------

@router.get(
    "",
    response_model=list[MedicationScheduleResponse],
)
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(MedicationSchedule)
        .where(
            MedicationSchedule.user_id == current_user.id,
        )
        .order_by(MedicationSchedule.created_at.desc())
    )

    schedules = result.scalars().all()

    return [
        serialize_schedule(schedule)
        for schedule in schedules
    ]


# --------------------------------------------------
# GET SINGLE REMINDER
# --------------------------------------------------

@router.get(
    "/{schedule_id}",
    response_model=MedicationScheduleResponse,
)
async def get_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(MedicationSchedule).where(
            MedicationSchedule.id == schedule_id,
            MedicationSchedule.user_id == current_user.id,
        )
    )

    schedule = result.scalar_one_or_none()

    if schedule is None:
        raise HTTPException(
            status_code=404,
            detail="Medication schedule not found.",
        )

    return serialize_schedule(schedule)


# --------------------------------------------------
# UPDATE REMINDER
# --------------------------------------------------

@router.patch(
    "/{schedule_id}",
    response_model=MedicationScheduleResponse,
)
async def update_schedule(
    schedule_id: str,
    payload: MedicationScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="At least one field must be provided.",
        )

    try:
        schedule = await update_medication_schedule(
            db,
            current_user.id,
            schedule_id,
            changes,
        )

        await db.commit()
        await db.refresh(schedule)

        return serialize_schedule(schedule)

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# DISABLE REMINDER
# --------------------------------------------------

@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        await disable_medication_schedule(
            db,
            current_user.id,
            schedule_id,
        )

        await db.commit()

        return None

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# GENERATE DUE DOSE RECORDS
# --------------------------------------------------

@router.post("/doses/generate")
async def generate_doses(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        created = await generate_due_doses(
            db,
            current_user.id,
        )

        await db.commit()

        return {
            "created_count": created,
            "message": "Due dose records generated.",
        }

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# GENERATE DUE DOSES + MARK MISSED DOSES
# --------------------------------------------------

@router.post("/doses/mark-missed")
async def process_missed_doses(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        # First generate due dose records.
        generated_count = await generate_due_doses(
            db,
            current_user.id,
        )

        # Then mark overdue pending doses as missed.
        missed_count = await mark_missed_doses(
            db,
            current_user.id,
        )

        await db.commit()

        return {
            "generated_count": generated_count,
            "missed_count": missed_count,
            "message": "Dose generation and missed-dose processing completed.",
        }

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# MARK DOSE AS TAKEN OR SKIPPED
# --------------------------------------------------

@router.patch(
    "/doses/{log_id}",
    response_model=MedicationLogResponse,
)
async def update_dose_status(
    log_id: str,
    payload: DoseActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        log = await mark_dose(
            db,
            current_user.id,
            log_id,
            payload.status,
        )

        await db.commit()
        await db.refresh(log)

        return log

    except Exception:
        await db.rollback()
        raise


# --------------------------------------------------
# MEDICATION ADHERENCE ANALYTICS
# --------------------------------------------------

@router.get(
    "/adherence",
    response_model=MedicationAdherenceResponse,
)
async def medication_adherence(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await get_adherence(
        db,
        current_user.id,
    )
