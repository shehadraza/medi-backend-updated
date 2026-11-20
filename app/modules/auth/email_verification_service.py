
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification import EmailVerificationToken
from app.models.user import User


VERIFICATION_TOKEN_EXPIRE_MINUTES = 30


def hash_verification_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_email_verification_token(
    db: AsyncSession,
    user: User,
) -> str:
    # Invalidate previous unused tokens for this user.
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )

    raw_token = secrets.token_urlsafe(48)

    verification_token = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_verification_token(raw_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=VERIFICATION_TOKEN_EXPIRE_MINUTES),
    )

    db.add(verification_token)
    await db.commit()

    return raw_token


async def verify_email_token(
    db: AsyncSession,
    raw_token: str,
) -> User:
    token_hash = hash_verification_token(raw_token)

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )

    verification_token = result.scalar_one_or_none()

    if not verification_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link.",
        )

    now = datetime.now(timezone.utc)
    expires_at = verification_token.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if verification_token.used_at is not None or expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link.",
        )

    user_result = await db.execute(
        select(User).where(User.id == verification_token.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to verify this account.",
        )

    user.is_verified = True
    verification_token.used_at = now

    await db.commit()
    await db.refresh(user)

    return user
