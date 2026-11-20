"""Authenticated endpoints for private daily health check-ins."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.health.checkin_schemas import (
    CheckInCreateRequest, CheckInListResponse, CheckInPatchRequest, CheckInResponse,
)
from app.modules.health.checkin_service import (
    create_checkin, delete_checkin, get_checkin, list_checkins, update_checkin,
)


router = APIRouter(prefix="/health/check-ins", tags=["Daily Health Check-ins"])


@router.post("", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
async def create_daily_checkin(
    payload: CheckInCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_checkin(db, str(current_user.id), payload)
        await db.commit()
        return result
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=503, detail="Check-in service is temporarily unavailable.") from None


@router.get("", response_model=CheckInListResponse)
async def read_daily_checkins(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    try:
        items = await list_checkins(
            db, str(current_user.id), start_date=start_date, end_date=end_date,
            limit=limit, offset=offset,
        )
        return {"items": items, "limit": limit, "offset": offset}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Check-in service is temporarily unavailable.") from None


@router.get("/{checkin_id}", response_model=CheckInResponse)
async def read_daily_checkin(
    checkin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_checkin(db, str(current_user.id), checkin_id)


@router.patch("/{checkin_id}", response_model=CheckInResponse)
async def patch_daily_checkin(
    checkin_id: str,
    payload: CheckInPatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await update_checkin(db, str(current_user.id), checkin_id, payload)
        await db.commit()
        return result
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=503, detail="Check-in service is temporarily unavailable.") from None


@router.delete("/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_daily_checkin(
    checkin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_checkin(db, str(current_user.id), checkin_id)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=503, detail="Check-in service is temporarily unavailable.") from None
