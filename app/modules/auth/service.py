
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.modules.auth.repository import (
    create_user,
    get_user_by_email,
)
from app.core.security import hash_password, verify_password


async def register_user(
    db: AsyncSession,
    full_name: str,
    email: str,
    password: str,
):
    existing_user = await get_user_by_email(db, email)

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    password_hashed = hash_password(password)

    return await create_user(
        db=db,
        full_name=full_name,
        email=email,
        password_hash=password_hashed,
    )


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
):
    user = await get_user_by_email(db, email)

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
     raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This account is disabled.",
    )

    if not user.is_verified:
      raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Please verify your email before logging in.",
    )

    return user

