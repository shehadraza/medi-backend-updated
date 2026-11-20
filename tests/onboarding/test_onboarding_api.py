
import uuid
import pytest_asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import engine, get_db
from app.core.dependencies import get_current_user
from app.models.user import User


@pytest_asyncio.fixture(loop_scope="session")
async def api_client():
    user_id = str(uuid.uuid4())

    async with engine.connect() as connection:
        transaction = await connection.begin()

        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as db:

                user = User(
                    id=user_id,
                    full_name="MEDI API Test",
                    email=f"medi-api-{user_id}@example.com",
                    password_hash="test-only-not-a-real-password",
                    is_active=True,
                    is_verified=True,
                )

                db.add(user)
                await db.flush()

                async def override_get_db():
                    yield db

                async def override_get_current_user():
                    return user

                app.dependency_overrides[get_db] = override_get_db
                app.dependency_overrides[
                    get_current_user
                ] = override_get_current_user

                transport = ASGITransport(app=app)

                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                ) as client:
                    yield client, user

        finally:
            app.dependency_overrides.clear()

            if transaction.is_active:
                await transaction.rollback()

@pytest.mark.asyncio(loop_scope="session")
async def test_get_empty_onboarding_profile(api_client):
    client, _ = api_client

    response = await client.get("/onboarding/profile")

    assert response.status_code == 200
    assert response.json()["profile"] is None
    assert response.json()["onboarding_completed"] is False
    assert response.json()["ai_personalization_consent"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_save_and_retrieve_health_profile(api_client):
    client, _ = api_client

    payload = {
        "sleep_hours": 7.5,
        "sleep_quality": "good",
        "water_intake_liters": 2.5,
        "activity_level": "moderate",
        "exercise_days_per_week": 4,
        "screen_time_hours": 6,
        "diet_type": "balanced",
        "junk_food_frequency": "sometimes",
        "stress_level": "moderate",
        "health_goals": ["Better sleep", "Fitness"],
        "additional_notes": "Daily walking",
    }

    saved = await client.put("/onboarding/profile", json=payload)

    assert saved.status_code == 200
    assert saved.json()["profile"]["sleep_hours"] == 7.5
    assert saved.json()["profile"]["health_goals"] == [
        "Better sleep",
        "Fitness",
    ]

    retrieved = await client.get("/onboarding/profile")

    assert retrieved.status_code == 200
    assert retrieved.json()["profile"] == saved.json()["profile"]


@pytest.mark.asyncio(loop_scope="session")
async def test_partial_profile_update_preserves_existing_data(api_client):
    client, _ = api_client

    first = await client.put(
        "/onboarding/profile",
        json={
            "sleep_hours": 7,
            "water_intake_liters": 2,
        },
    )

    assert first.status_code == 200

    updated = await client.put(
        "/onboarding/profile",
        json={"sleep_hours": 8},
    )

    assert updated.status_code == 200
    assert updated.json()["profile"]["sleep_hours"] == 8
    assert updated.json()["profile"]["water_intake_liters"] == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_ai_personalization_consent(api_client):
    client, _ = api_client

    enabled = await client.patch(
        "/onboarding/consent",
        json={"enabled": True},
    )

    assert enabled.status_code == 200
    assert enabled.json()["ai_personalization_consent"] is True

    disabled = await client.patch(
        "/onboarding/consent",
        json={"enabled": False},
    )

    assert disabled.status_code == 200
    assert disabled.json()["ai_personalization_consent"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_complete_onboarding_requires_profile(api_client):
    client, _ = api_client

    response = await client.post("/onboarding/complete")

    assert response.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_complete_onboarding_after_profile_creation(api_client):
    client, _ = api_client

    saved = await client.put(
        "/onboarding/profile",
        json={"sleep_hours": 7},
    )

    assert saved.status_code == 200

    completed = await client.post("/onboarding/complete")

    assert completed.status_code == 200
    assert completed.json()["onboarding_completed"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_onboarding_rejects_unauthenticated_requests():
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/onboarding/profile")

    assert response.status_code == 401
