
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin
from app.db.session import get_db
from app.models.medicine_catalog import MedicineCatalog
from app.models.user import User

from app.modules.medicines.catalog_schemas import (
    CatalogAdminResponse,
    CatalogCreateRequest,
    CatalogPublicResponse,
    CatalogUpdateRequest,
    CatalogVerifyRequest,
    CatalogListResponse,
)


public_router = APIRouter(
    prefix="/medicine-catalog",
    tags=["Medicine Catalog"],
)

admin_router = APIRouter(
    prefix="/admin/medicine-catalog",
    tags=["Admin - Medicine Catalog"],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_price_source(data: dict) -> None:
    price = data.get("price_amount")

    if price is not None:
        source_name = data.get("source_name")
        source_url = data.get("source_url")
        source_reference = data.get("source_reference")

        if not source_name or not (source_url or source_reference):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "A medicine price requires a source name and "
                    "a source URL or source reference."
                ),
            )


def validate_verification_source(
    source_name: str,
    source_url: str | None,
    source_reference: str | None,
) -> None:
    if not source_name.strip():
        raise HTTPException(
            status_code=422,
            detail="A verification source name is required.",
        )

    if not (
        (source_url and source_url.strip())
        or (source_reference and source_reference.strip())
    ):
        raise HTTPException(
            status_code=422,
            detail="A source URL or source reference is required.",
        )


def apply_search(query, search: str | None):
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                MedicineCatalog.generic_name.ilike(term),
                MedicineCatalog.brand_name.ilike(term),
                MedicineCatalog.manufacturer.ilike(term),
            )
        )

    return query


# ---------------------------------------------------------
# PATIENT-FACING VERIFIED CATALOG
# ---------------------------------------------------------

@public_router.get(
    "",
    response_model=CatalogListResponse,
)
async def search_medicine_catalog(
    search: str | None = Query(default=None, max_length=150),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    filters = (
        MedicineCatalog.is_verified.is_(True),
        MedicineCatalog.is_published.is_(True),
    )

    count_query = (
        select(func.count())
        .select_from(MedicineCatalog)
        .where(*filters)
    )

    if search and search.strip():
        count_query = apply_search(count_query, search)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    items_query = (
        select(MedicineCatalog)
        .where(*filters)
        .order_by(MedicineCatalog.generic_name.asc())
        .limit(limit)
        .offset(offset)
    )

    items_query = apply_search(items_query, search)

    result = await db.execute(items_query)
    items = result.scalars().all()

    return CatalogListResponse(
        total=total,
        items=[
            CatalogPublicResponse.model_validate(item)
            for item in items
        ],
    )


@public_router.get(
    "/{catalog_id}",
    response_model=CatalogPublicResponse,
)
async def get_public_medicine(
    catalog_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog).where(
            MedicineCatalog.id == catalog_id,
            MedicineCatalog.is_verified.is_(True),
            MedicineCatalog.is_published.is_(True),
        )
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Medicine not found.",
        )

    return CatalogPublicResponse.model_validate(item)


# ---------------------------------------------------------
# ADMIN CATALOG MANAGEMENT
# ---------------------------------------------------------

@admin_router.get("")
async def admin_list_catalog(
    search: str | None = Query(default=None, max_length=150),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(MedicineCatalog)
        .order_by(MedicineCatalog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    query = apply_search(query, search)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            CatalogAdminResponse.model_validate(item)
            for item in items
        ],
        "limit": limit,
        "offset": offset,
    }


@admin_router.post(
    "",
    response_model=CatalogAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_entry(
    payload: CatalogCreateRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()

    validate_price_source(data)

    item = MedicineCatalog(
        **data,
        created_by=current_admin.id,
        updated_by=current_admin.id,
        verified_by=None,
        is_verified=False,
        is_published=False,
    )

    db.add(item)
    await db.commit()
    await db.refresh(item)

    return CatalogAdminResponse.model_validate(item)


@admin_router.get(
    "/{catalog_id}",
    response_model=CatalogAdminResponse,
)
async def admin_get_catalog_entry(
    catalog_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog).where(
            MedicineCatalog.id == catalog_id
        )
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Medicine not found.")

    return CatalogAdminResponse.model_validate(item)


@admin_router.patch(
    "/{catalog_id}",
    response_model=CatalogAdminResponse,
)
async def update_catalog_entry(
    catalog_id: str,
    payload: CatalogUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog)
        .where(MedicineCatalog.id == catalog_id)
        .with_for_update()
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Medicine not found.")

    changes = payload.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="At least one field must be provided.",
        )

    if "generic_name" in changes:
        if changes["generic_name"] is None or not changes["generic_name"].strip():
            raise HTTPException(
                status_code=422,
                detail="Generic name cannot be empty.",
            )

    proposed_data = {
        field: getattr(item, field)
        for field in CatalogCreateRequest.model_fields
    }
    proposed_data.update(changes)

    validate_price_source(proposed_data)

    for field, value in changes.items():
        setattr(item, field, value)

    # Any content change invalidates previous verification/publication.
    item.is_verified = False
    item.is_published = False
    item.verified_by = None
    item.last_verified_at = None
    item.updated_by = current_admin.id

    await db.commit()
    await db.refresh(item)

    return CatalogAdminResponse.model_validate(item)


@admin_router.post(
    "/{catalog_id}/verify",
    response_model=CatalogAdminResponse,
)
async def verify_catalog_entry(
    catalog_id: str,
    payload: CatalogVerifyRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog)
        .where(MedicineCatalog.id == catalog_id)
        .with_for_update()
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Medicine not found.")

    validate_verification_source(
        payload.source_name,
        payload.source_url,
        payload.source_reference,
    )

    verified_at = payload.last_verified_at

    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="Verification timestamp must include a timezone.",
        )

    if verified_at > utc_now():
        raise HTTPException(
            status_code=422,
            detail="Verification timestamp cannot be in the future.",
        )

    if item.price_amount is not None and not (
        payload.source_url or payload.source_reference
    ):
        raise HTTPException(
            status_code=422,
            detail="A price source is required to verify this medicine.",
        )

    item.source_name = payload.source_name.strip()
    item.source_url = payload.source_url
    item.source_reference = payload.source_reference
    item.last_verified_at = verified_at
    item.verified_by = current_admin.id
    item.updated_by = current_admin.id
    item.is_verified = True

    # Verification alone does not publish the entry.
    item.is_published = False

    await db.commit()
    await db.refresh(item)

    return CatalogAdminResponse.model_validate(item)


@admin_router.post(
    "/{catalog_id}/publish",
    response_model=CatalogAdminResponse,
)
async def publish_catalog_entry(
    catalog_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog)
        .where(MedicineCatalog.id == catalog_id)
        .with_for_update()
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Medicine not found.")

    if not item.is_verified or item.last_verified_at is None:
        raise HTTPException(
            status_code=409,
            detail="Medicine must be verified before publication.",
        )

    validate_verification_source(
        item.source_name or "",
        item.source_url,
        item.source_reference,
    )

    item.is_published = True
    item.updated_by = current_admin.id

    await db.commit()
    await db.refresh(item)

    return CatalogAdminResponse.model_validate(item)


@admin_router.post(
    "/{catalog_id}/archive",
    response_model=CatalogAdminResponse,
)
async def archive_catalog_entry(
    catalog_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MedicineCatalog)
        .where(MedicineCatalog.id == catalog_id)
        .with_for_update()
    )

    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(status_code=404, detail="Medicine not found.")

    item.is_published = False
    item.updated_by = current_admin.id

    await db.commit()
    await db.refresh(item)

    return CatalogAdminResponse.model_validate(item)
