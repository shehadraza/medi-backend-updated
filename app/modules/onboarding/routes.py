
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.onboarding.schemas import (
    AIPersonalizationConsentRequest,
    ConsentStatusResponse,
    HealthProfileData,
    HealthProfileResponse,
    OnboardingCompleteResponse,
    ProactiveConsentRequest,
)
from app.modules.onboarding.service import (
    complete_onboarding,
    get_consent_status,
    get_onboarding_state,
    update_ai_personalization_consent,
    update_onboarding_profile,
    update_proactive_consent,
)


router = APIRouter(
    prefix="/onboarding",
    tags=["Personalized Health Onboarding"],
)


@router.get("/consent", response_model=ConsentStatusResponse)
async def read_consent_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_consent_status(db, str(current_user.id))


@router.get(
    "/profile",
    response_model=HealthProfileResponse,
)
async def read_health_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_onboarding_state(db, current_user.id)


@router.put(
    "/profile",
    response_model=HealthProfileResponse,
)
async def save_onboarding_profile(
    payload: HealthProfileData,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await update_onboarding_profile(
            db=db,
            user_id=current_user.id,
            profile_data=payload.model_dump(exclude_unset=True),
        )
        await db.commit()

        return await get_onboarding_state(db, current_user.id)

    except Exception:
        await db.rollback()
        raise


@router.patch(
    "/consent",
    response_model=HealthProfileResponse,
)
async def update_personalization_consent(
    payload: AIPersonalizationConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await update_ai_personalization_consent(
            db=db,
            user_id=current_user.id,
            enabled=payload.enabled,
        )
        await db.commit()

        return await get_onboarding_state(db, current_user.id)

    except Exception:
        await db.rollback()
        raise


@router.patch("/consent/proactive-health-analysis", response_model=ConsentStatusResponse)
async def update_proactive_health_analysis_consent(
    payload: ProactiveConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await update_proactive_consent(
            db, str(current_user.id), scope="health_analysis", enabled=payload.enabled,
        )
        await db.commit()
        return await get_consent_status(db, str(current_user.id))
    except Exception:
        await db.rollback()
        raise


@router.patch("/consent/proactive-wellness-notifications", response_model=ConsentStatusResponse)
async def update_proactive_wellness_notifications_consent(
    payload: ProactiveConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await update_proactive_consent(
            db, str(current_user.id), scope="wellness_notifications", enabled=payload.enabled,
        )
        await db.commit()
        return await get_consent_status(db, str(current_user.id))
    except Exception:
        await db.rollback()
        raise


@router.post(
    "/complete",
    response_model=OnboardingCompleteResponse,
)
async def mark_onboarding_complete(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await complete_onboarding(db, current_user.id)
        await db.commit()

        return {
            "message": "Health onboarding completed successfully.",
            "onboarding_completed": True,
        }

    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception:
        await db.rollback()
        raise
