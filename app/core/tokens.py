
from datetime import datetime, timedelta, timezone
import secrets

from app.core.config import settings


def create_access_token() -> str:
    return secrets.token_urlsafe(48)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def get_access_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )


def get_refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
