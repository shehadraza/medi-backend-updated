
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_super_admin
from app.db.session import get_db
from app.models.user import User
from app.models.ai import KnowledgeDocument, KnowledgeSource, KnowledgeSyncState
from app.modules.ai.knowledge_sync import SOURCE_URL
from app.modules.ai.source_adapters import SOURCE_ADAPTERS

from app.modules.admin.schemas import (
    AdminActionResponse,
    AdminUserListResponse,
    AdminUserResponse,
)

router = APIRouter(prefix="/admin", tags=["Admin Management"])


@router.get("/knowledge-sources-status")
async def get_knowledge_sources_status(
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Read-only, sanitized health summary for code-configured knowledge adapters."""
    results = []
    for adapter in SOURCE_ADAPTERS:
        configured = adapter.acquisition_enabled and (
            adapter.key != "pubmed" or bool(settings.AI_NCBI_CONTACT_EMAIL)
        )
        source_result = await db.execute(select(KnowledgeSource).where(
            KnowledgeSource.name == adapter.display_name,
            KnowledgeSource.source_url == adapter.source_url,
        ))
        source = source_result.scalar_one_or_none()
        state = await db.get(KnowledgeSyncState, source.id) if source else None
        counts = {}
        if source:
            count_result = await db.execute(
                select(KnowledgeDocument.status, func.count())
                .where(KnowledgeDocument.source_id == source.id)
                .group_by(KnowledgeDocument.status)
            )
            counts = {str(status): int(count) for status, count in count_result.all()}
        results.append({
            "key": adapter.key,
            "name": adapter.display_name,
            "publisher": adapter.publisher,
            "integration_method": adapter.integration_method,
            "policy_url": adapter.policy_url,
            "configured": configured,
            "acquisition_enabled": adapter.acquisition_enabled,
            "user_facing_enabled": adapter.user_facing_enabled,
            "sync_state": "disabled" if not configured else "error" if state and state.last_error_code else "healthy" if state and state.last_success_at else "not_started",
            "last_attempt_at": state.last_attempt_at if state else None,
            "last_success_at": state.last_success_at if state else None,
            "next_sync_at": state.next_sync_at if state else None,
            "last_error_code": state.last_error_code if state else None,
            "failure_count": state.failure_count if state else 0,
            "documents_seen": state.documents_seen if state else 0,
            "document_counts": counts,
        })
    return {"sources": results, "worker_enabled": settings.AI_KNOWLEDGE_SYNC_ENABLED}


@router.get("/knowledge-sync-status")
async def get_knowledge_sync_status(
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Read-only sanitized source health and document counts for the Super Admin."""
    source_result = await db.execute(select(KnowledgeSource).where(
        KnowledgeSource.name == "MedlinePlus Web Service",
        KnowledgeSource.source_url == SOURCE_URL,
    ))
    source = source_result.scalar_one_or_none()
    if source is None:
        return {"configured": True, "source_name": "MedlinePlus Web Service", "sync_state": "not_started", "document_counts": {}}
    state = await db.get(KnowledgeSyncState, source.id)
    count_result = await db.execute(
        select(KnowledgeDocument.status, func.count())
        .where(KnowledgeDocument.source_id == source.id)
        .group_by(KnowledgeDocument.status)
    )
    unseen_filter = KnowledgeDocument.last_seen_at.is_(None)
    if state and state.last_success_at:
        unseen_filter = unseen_filter | (KnowledgeDocument.last_seen_at < state.last_success_at)
    unseen_result = await db.execute(select(func.count()).select_from(KnowledgeDocument).where(
        KnowledgeDocument.source_id == source.id,
        KnowledgeDocument.status == "published",
        unseen_filter,
    ))
    return {
        "configured": True,
        "source_name": source.name,
        "publisher": source.publisher,
        "sync_state": "error" if state and state.last_error_code else "healthy" if state and state.last_success_at else "not_started",
        "last_attempt_at": state.last_attempt_at if state else None,
        "last_success_at": state.last_success_at if state else None,
        "next_sync_at": state.next_sync_at if state else None,
        "last_error_code": state.last_error_code if state else None,
        "failure_count": state.failure_count if state else 0,
        "documents_seen": state.documents_seen if state else 0,
        "document_counts": {str(status): int(count) for status, count in count_result.all()},
        "published_not_seen_at_last_successful_sync": int(unseen_result.scalar_one()),
    }


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=100),
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    filters = []

    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                User.full_name.ilike(term),
                User.email.ilike(term),
            )
        )

    total_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(*filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    users = result.scalars().all()

    return AdminUserListResponse(
        items=[
            AdminUserResponse.model_validate(user)
            for user in users
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users/{user_id}/grant",
    response_model=AdminActionResponse,
)
async def grant_admin_access(
    user_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )
    target = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    configured_email = settings.MEDI_SUPER_ADMIN_EMAIL.strip().lower()

    if target.email.strip().lower() == configured_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The configured Super Admin account cannot be modified.",
        )

    if target.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin accounts cannot be modified through this endpoint.",
        )

    if not target.is_active or not target.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active, verified users can receive Admin access.",
        )

    if target.role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The user's current role cannot be changed.",
        )

    if target.role == "admin" and target.is_admin:
        return AdminActionResponse(
            message="User already has Admin access.",
            user=AdminUserResponse.model_validate(target),
        )

    target.role = "admin"
    target.is_admin = True

    await db.commit()
    await db.refresh(target)

    return AdminActionResponse(
        message="Admin access granted successfully.",
        user=AdminUserResponse.model_validate(target),
    )


@router.post(
    "/users/{user_id}/revoke",
    response_model=AdminActionResponse,
)
async def revoke_admin_access(
    user_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )
    target = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    configured_email = settings.MEDI_SUPER_ADMIN_EMAIL.strip().lower()

    if target.email.strip().lower() == configured_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The configured Super Admin account cannot be demoted.",
        )

    if target.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin accounts cannot be demoted through this endpoint.",
        )

    if target.role != "admin" or not target.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User does not currently have Admin access.",
        )

    target.role = "user"
    target.is_admin = False

    await db.commit()
    await db.refresh(target)

    return AdminActionResponse(
        message="Admin access revoked successfully.",
        user=AdminUserResponse.model_validate(target),
    )
