from __future__ import annotations

import hashlib
import hmac
import math
import time

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


def _digest(scope: str, identity: str) -> str:
    """Return a keyed digest; never persist raw email addresses or IPs."""
    secret = settings.SECRET_KEY.encode("utf-8")
    payload = f"{scope}:{identity.strip().lower()}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _window_start(now: float, window_seconds: int) -> int:
    return math.floor(now / window_seconds) * window_seconds


async def enforce_rate_limit(
    db: AsyncSession,
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    """
    PostgreSQL-backed fixed-window limiter.
    The UPSERT is atomic and shared by all application workers.
    """
    if limit < 1 or window_seconds < 1:
        raise ValueError("Rate limit values must be positive.")

    key = _digest(scope, identity)
    bucket = _window_start(time.time(), window_seconds)

    result = await db.execute(
        text(
            """
            INSERT INTO auth_rate_limits (key_digest, window_start, request_count)
            VALUES (:key_digest, to_timestamp(:window_start), 1)
            ON CONFLICT (key_digest)
            DO UPDATE SET
                window_start = EXCLUDED.window_start,
                request_count = CASE
                    WHEN auth_rate_limits.window_start = EXCLUDED.window_start
                    THEN auth_rate_limits.request_count + 1
                    ELSE 1
                END
            RETURNING request_count
            """
        ),
        {"key_digest": key, "window_start": bucket},
    )
    count = int(result.scalar_one())
    await db.commit()

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(window_seconds - (int(time.time()) % window_seconds))},
        )


def client_ip_identity(client_host: str | None) -> str:
    # Do not trust X-Forwarded-For unless a trusted-proxy policy is configured.
    return client_host or "unknown-client"
