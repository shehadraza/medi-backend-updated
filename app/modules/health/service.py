
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_data, decrypt_data
from app.models.health_profile import HealthProfile


ENCRYPTION_VERSION = 1


def _get_profile_aad(user_id: str) -> bytes:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("A valid user ID is required.")

    return f"medi:health-profile:v1:{user_id}".encode("utf-8")


def _serialize_profile(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        raise ValueError("Health profile must be a JSON object.")

    try:
        return json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Health profile contains invalid data.") from exc


def _deserialize_profile(data: str) -> dict[str, Any]:
    try:
        result = json.loads(data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("Stored health profile is invalid.") from exc

    if not isinstance(result, dict):
        raise RuntimeError("Stored health profile must be a JSON object.")

    return result


async def save_health_profile(
    db: AsyncSession,
    user_id: str,
    data: dict[str, Any],
) -> HealthProfile:
    aad = _get_profile_aad(user_id)
    plaintext = _serialize_profile(data)

    encrypted_data = encrypt_data(
        plaintext,
        associated_data=aad,
    )

    result = await db.execute(
        select(HealthProfile).where(
            HealthProfile.user_id == user_id
        )
    )

    profile = result.scalar_one_or_none()

    if profile is None:
        profile = HealthProfile(
            user_id=user_id,
            encrypted_data=encrypted_data,
            encryption_version=ENCRYPTION_VERSION,
        )
        db.add(profile)
    else:
        profile.encrypted_data = encrypted_data
        profile.encryption_version = ENCRYPTION_VERSION

    await db.flush()

    return profile


async def get_health_profile(
    db: AsyncSession,
    user_id: str,
) -> dict[str, Any] | None:
    aad = _get_profile_aad(user_id)

    result = await db.execute(
        select(HealthProfile).where(
            HealthProfile.user_id == user_id
        )
    )

    profile = result.scalar_one_or_none()

    if profile is None:
        return None

    if profile.encryption_version != ENCRYPTION_VERSION:
        raise RuntimeError("Unsupported health profile encryption version.")

    plaintext = decrypt_data(
        profile.encrypted_data,
        associated_data=aad,
    )

    return _deserialize_profile(plaintext)
