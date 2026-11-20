
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.config import settings
from app.models.user import User
from app.modules.auth.session_service import get_active_session

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    session = await get_active_session(db, credentials.credentials)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session.",
        )

    result = await db.execute(
        select(User).where(
            User.id == session.user_id,
            User.is_active.is_(True),
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    configured_email = settings.MEDI_SUPER_ADMIN_EMAIL.strip().lower()
    user_email = current_user.email.strip().lower()

    is_super_admin = (
        bool(configured_email)
        and current_user.role == "super_admin"
        and current_user.is_admin
        and user_email == configured_email
    )

    is_regular_admin = (
        current_user.role == "admin"
        and current_user.is_admin
    )

    if not (is_super_admin or is_regular_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator permission required.",
        )

    return current_user


async def get_current_super_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    configured_email = settings.MEDI_SUPER_ADMIN_EMAIL.strip().lower()

    if not configured_email:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Super Admin identity is not configured.",
        )

    if (
        current_user.role != "super_admin"
        or not current_user.is_admin
        or current_user.email.strip().lower() != configured_email
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin permission required.",
        )

    return current_user
