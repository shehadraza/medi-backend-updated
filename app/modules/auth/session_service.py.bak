
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import UserSession

from app.core.tokens import (
    create_access_token,
    create_refresh_token,
    get_access_token_expiry,
    get_refresh_token_expiry,
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_user_session(db: AsyncSession, user_id: str):
    access_token = create_access_token()
    refresh_token = create_refresh_token()

    access_expiry = get_access_token_expiry()
    refresh_expiry = get_refresh_token_expiry()

    session = UserSession(
        user_id=user_id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        access_expires_at=access_expiry,
        refresh_expires_at=refresh_expiry,
    )

    db.add(session)
    await db.commit()

    expires_in = max(
        0,
        int((access_expiry - datetime.now(timezone.utc)).total_seconds()),
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


async def get_active_session(db: AsyncSession, access_token: str):
    result = await db.execute(
        select(UserSession).where(
            UserSession.access_token_hash == hash_token(access_token),
            UserSession.revoked_at.is_(None),
            UserSession.access_expires_at > datetime.now(timezone.utc),
        )
    )

    return result.scalar_one_or_none()


async def revoke_user_session(db: AsyncSession, access_token: str):
    session = await get_active_session(db, access_token)

    if session is None:
        return False

    session.revoked_at = datetime.now(timezone.utc)

    await db.commit()

    return True
async def get_session_by_refresh_token(db: AsyncSession, refresh_token: str):
    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == hash_token(refresh_token),
            UserSession.revoked_at.is_(None),
            UserSession.refresh_expires_at > datetime.now(timezone.utc)
        )
    )
    return result.scalar_one_or_none()
async def rotate_refresh_token(db: AsyncSession, refresh_token: str):
    session = await get_session_by_refresh_token(db, refresh_token)

    if session is None:
        return None

    new_access_token = create_access_token()
    new_refresh_token = create_refresh_token()

    session.access_token_hash = hash_token(new_access_token)
    session.refresh_token_hash = hash_token(new_refresh_token)
    session.access_expires_at = get_access_token_expiry()
    session.refresh_expires_at = get_refresh_token_expiry()

    await db.commit()

    expires_in = max(
        0,
        int((session.access_expires_at - datetime.now(timezone.utc)).total_seconds())
    )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in
    }