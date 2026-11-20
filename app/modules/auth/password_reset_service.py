
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset import PasswordResetToken
from sqlalchemy import update

from app.models.user import User
from app.models.session import UserSession
from app.core.security import hash_password


RESET_TOKEN_EXPIRE_MINUTES = 30


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_password_reset_token(
    db: AsyncSession,
    user_id: str
) -> str:
    now = datetime.now(timezone.utc)

    # Invalidate previous unused reset tokens.
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None)
        )
    )

    old_tokens = result.scalars().all()

    for old_token in old_tokens:
        old_token.used_at = now

    # Generate a new unpredictable token.
    raw_token = secrets.token_urlsafe(48)

    reset_record = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_reset_token(raw_token),
        expires_at=now + timedelta(
            minutes=RESET_TOKEN_EXPIRE_MINUTES
        )
    )

    db.add(reset_record)
    await db.commit()

    # Return raw token only once. Never store it in the database.
    return raw_token


async def get_valid_password_reset_token(
    db: AsyncSession,
    raw_token: str
):
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_reset_token(raw_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now
        )
    )

    return result.scalar_one_or_none()

async def reset_user_password(
    db: AsyncSession,
    raw_token: str,
    new_password: str
) -> bool:
    now = datetime.now(timezone.utc)

    # Lock the token row to prevent simultaneous reuse.
    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == hash_reset_token(raw_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now
        )
        .with_for_update()
    )

    reset_record = result.scalar_one_or_none()

    if reset_record is None:
        return False

    user_result = await db.execute(
        select(User).where(User.id == reset_record.user_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        return False

    user.password_hash = hash_password(new_password)
    reset_record.used_at = now

    # Revoke every existing login session for this user.
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None)
        )
        .values(revoked_at=now)
    )

    await db.commit()
    return True
