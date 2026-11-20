
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models.user import User
from app.models.health_profile import HealthProfile
from app.modules.health.service import (
    save_health_profile,
    get_health_profile,
)


@pytest.mark.asyncio
async def test_health_profile_database_round_trip():
    user_id = str(uuid.uuid4())

    bangla_note = (
        "\u0986\u09ae\u09bf "
        "\u09aa\u09cd\u09b0\u09a4\u09bf\u09a6\u09bf\u09a8 "
        "\u09b8\u0995\u09be\u09b2\u09c7 "
        "\u09b9\u09be\u0981\u099f\u09bf\u0964"
    )

    profile_data = {
        "sleep_hours": 7,
        "water_intake_liters": 2.5,
        "exercise": "Walking",
        "notes": bangla_note,
    }

    async with engine.connect() as connection:
        transaction = await connection.begin()

        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as db:

                user = User(
                    id=user_id,
                    full_name="MEDI Integration Test",
                    email=f"medi-test-{user_id}@example.com",
                    password_hash="test-only-not-a-real-password",
                    is_active=True,
                    is_verified=True,
                )

                db.add(user)
                await db.flush()

                saved = await save_health_profile(
                    db,
                    user_id,
                    profile_data,
                )

                assert saved.user_id == user_id
                assert saved.encrypted_data
                assert bangla_note not in saved.encrypted_data

                stored = await db.execute(
                    select(HealthProfile).where(
                        HealthProfile.user_id == user_id
                    )
                )

                database_profile = stored.scalar_one()

                assert database_profile.encrypted_data == saved.encrypted_data

                loaded = await get_health_profile(db, user_id)

                assert loaded == profile_data
                assert loaded["notes"] == bangla_note

                other_user_profile = await get_health_profile(
                    db,
                    str(uuid.uuid4()),
                )

                assert other_user_profile is None

        finally:
            if transaction.is_active:
                await transaction.rollback()
