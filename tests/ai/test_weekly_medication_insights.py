import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.db.session import engine, get_db
from app.main import app
from app.models.health_profile import HealthProfile
from app.models.medication import Medication, MedicationLog
from app.models.user import User
from app.modules.ai.weekly_insights import (
    _aggregate_event_groups,
    _weekly_period,
    get_weekly_medication_insight,
)


UTC = timezone.utc


class Result:
    def __init__(self, *, consent=None, rows=()):
        self.consent = consent
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.consent

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def event(record_count, first_status, last_status=None):
    return SimpleNamespace(
        record_count=record_count,
        first_status=first_status,
        last_status=first_status if last_status is None else last_status,
    )


def test_weekly_period_is_previous_seven_complete_local_dates():
    now = datetime(2026, 4, 10, 15, tzinfo=UTC)
    tz, start_utc, end_utc = _weekly_period(now, "Asia/Dhaka")
    assert tz.key == "Asia/Dhaka"
    assert start_utc.astimezone(tz).isoformat() == "2026-04-03T00:00:00+06:00"
    assert end_utc.astimezone(tz).isoformat() == "2026-04-10T00:00:00+06:00"
    assert end_utc - start_utc == timedelta(days=7)


def test_weekly_period_respects_daylight_saving_timezone_boundaries():
    now = datetime(2026, 3, 15, 12, tzinfo=UTC)
    tz, start_utc, end_utc = _weekly_period(now, "America/New_York")
    assert start_utc.astimezone(tz).isoformat() == "2026-03-08T00:00:00-05:00"
    assert end_utc.astimezone(tz).isoformat() == "2026-03-15T00:00:00-04:00"
    assert end_utc - start_utc == timedelta(hours=167)


def test_timezone_unavailable_is_rejected_before_database_access():
    with pytest.raises(HTTPException) as error:
        _weekly_period(datetime.now(UTC), "Not/A_Real_Zone")
    assert error.value.status_code == 422


def test_aggregate_counts_only_explicit_status_and_deduplicates_events():
    counts = _aggregate_event_groups([
        event(2, "taken"),
        event(1, "missed"),
        event(1, "skipped"),
        event(1, "pending"),
        event(1, "cancelled"),
        event(2, "taken", "missed"),
        event(1, "future_status"),
    ])
    assert counts == {
        "scheduled_doses": 6,
        "taken_doses": 1,
        "missed_doses": 1,
        "skipped_doses": 1,
        "pending_doses": 1,
        "cancelled_doses": 1,
        "unclassified_doses": 2,
        "duplicate_records_ignored": 2,
        "adherence_denominator": 3,
        "adherence_percentage": 33.33,
    }


def test_empty_or_only_pending_records_have_unavailable_adherence():
    empty = _aggregate_event_groups([])
    pending = _aggregate_event_groups([event(1, "pending")])
    assert empty["scheduled_doses"] == 0
    assert empty["adherence_percentage"] is None
    assert pending["pending_doses"] == 1
    assert pending["missed_doses"] == 0
    assert pending["adherence_percentage"] is None


@pytest.mark.asyncio
async def test_consent_denial_precedes_any_medication_log_query():
    db = FakeDB([Result(consent=False)])
    with pytest.raises(HTTPException) as error:
        await get_weekly_medication_insight(
            db,
            "owner-1",
            timezone_name="Asia/Dhaka",
            now=datetime(2026, 4, 10, 15, tzinfo=UTC),
        )
    assert error.value.status_code == 403
    assert len(db.statements) == 1
    assert "ai_personalization_consent" in str(db.statements[0])


@pytest.mark.asyncio
async def test_interactive_consent_is_sufficient_for_user_requested_summary():
    db = FakeDB([Result(consent=True), Result(rows=[])])
    result = await get_weekly_medication_insight(
        db,
        "owner-1",
        timezone_name="Asia/Dhaka",
        now=datetime(2026, 4, 10, 15, tzinfo=UTC),
    )
    assert result["recorded_facts"]["adherence_percentage"] is None
    assert "proactive_health_analysis_consent" not in str(db.statements[0])
    assert "unrecorded_doses_not_inferred" in result["observations"]


@pytest.mark.asyncio
async def test_dose_query_is_user_scoped_and_uses_half_open_utc_period():
    now = datetime(2026, 4, 10, 15, tzinfo=UTC)
    db = FakeDB([Result(consent=True), Result(rows=[])])
    await get_weekly_medication_insight(
        db, "owner-1", timezone_name="Asia/Dhaka", now=now,
    )
    sql = str(db.statements[1])
    assert "medication_logs.user_id" in sql
    assert "medication_logs.scheduled_at >=" in sql
    assert "medication_logs.scheduled_at <" in sql
    assert "FOR UPDATE" not in sql
    assert "FOR UPDATE" in str(db.statements[0])


@pytest.mark.asyncio
async def test_authenticated_api_returns_summary_using_only_fake_database():
    owner = SimpleNamespace(id="authenticated-owner")
    db = FakeDB([Result(consent=True), Result(rows=[event(1, "taken")])])

    async def current_user():
        return owner

    async def current_db():
        yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/ai/insights/weekly-medication",
                params={"timezone_name": "Asia/Dhaka"},
            )
        assert response.status_code == 200
        assert response.json()["recorded_facts"]["taken_doses"] == 1
        assert "authenticated-owner" in str(db.statements[0].compile().params)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_authenticated_api_rejects_invalid_timezone_without_record_query():
    owner = SimpleNamespace(id="authenticated-owner")
    db = FakeDB([])

    async def current_user():
        return owner

    async def current_db():
        yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/ai/insights/weekly-medication",
                params={"timezone_name": "Not/A_Real_Zone"},
            )
        assert response.status_code == 422
        assert db.statements == []
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def weekly_db():
    owner = User(
        id=str(uuid.uuid4()),
        full_name="Weekly Insight Test",
        email=f"weekly-{uuid.uuid4()}@example.test",
        password_hash="test-only-hash",
        is_active=True,
        is_verified=True,
    )
    other = User(
        id=str(uuid.uuid4()),
        full_name="Other Weekly Test",
        email=f"weekly-other-{uuid.uuid4()}@example.test",
        password_hash="test-only-hash",
        is_active=True,
        is_verified=True,
    )
    now = datetime.now(UTC)
    _, start_utc, end_utc = _weekly_period(now, "Asia/Dhaka")

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                db.add_all([owner, other])
                await db.flush()
                db.add_all([
                    HealthProfile(
                        user_id=owner.id,
                        encrypted_data="test-ciphertext-not-decrypted",
                        ai_personalization_consent=True,
                        proactive_health_analysis_consent=False,
                    ),
                    HealthProfile(
                        user_id=other.id,
                        encrypted_data="test-ciphertext-not-decrypted",
                        ai_personalization_consent=True,
                    ),
                ])
                owner_med = Medication(
                    id=str(uuid.uuid4()), user_id=owner.id,
                    encrypted_data="test-ciphertext-not-decrypted", status="active",
                )
                other_med = Medication(
                    id=str(uuid.uuid4()), user_id=other.id,
                    encrypted_data="test-ciphertext-not-decrypted", status="active",
                )
                db.add_all([owner_med, other_med])
                await db.flush()

                logs = [
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=start_utc, status="taken",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=start_utc, status="taken",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=start_utc + timedelta(days=1), status="missed",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=start_utc + timedelta(days=2), status="pending",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=start_utc + timedelta(days=3), status="cancelled",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=end_utc - timedelta(seconds=1), status="skipped",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=end_utc, status="taken",
                    ),
                    MedicationLog(
                        medication_id=owner_med.id, user_id=owner.id,
                        scheduled_at=now + timedelta(hours=1), status="taken",
                    ),
                    MedicationLog(
                        medication_id=other_med.id, user_id=other.id,
                        scheduled_at=start_utc, status="taken",
                    ),
                ]
                db.add_all(logs)
                await db.flush()
                yield db, owner, other, start_utc, end_utc
        finally:
            if transaction.is_active:
                await transaction.rollback()


@pytest.mark.asyncio
async def test_postgres_integration_aggregates_owned_records_and_excludes_boundaries(weekly_db):
    db, owner, _, start_utc, end_utc = weekly_db
    insight = await get_weekly_medication_insight(
        db,
        owner.id,
        timezone_name="Asia/Dhaka",
        now=datetime.now(UTC),
    )
    facts = insight["recorded_facts"]
    assert insight["period_start_utc"] == start_utc
    assert insight["period_end_utc_exclusive"] == end_utc
    assert facts["scheduled_doses"] == 4
    assert facts["taken_doses"] == 1
    assert facts["missed_doses"] == 1
    assert facts["skipped_doses"] == 1
    assert facts["pending_doses"] == 1
    assert facts["cancelled_doses"] == 1
    assert facts["duplicate_records_ignored"] == 1
    assert facts["adherence_percentage"] == 33.33


@pytest.mark.asyncio
async def test_postgres_integration_revoked_consent_blocks_record_access(weekly_db):
    db, owner, _, _, _ = weekly_db
    profile = (await db.execute(
        select(HealthProfile).where(HealthProfile.user_id == owner.id)
    )).scalar_one()
    profile.ai_personalization_consent = False
    await db.flush()

    with pytest.raises(HTTPException) as error:
        await get_weekly_medication_insight(
            db,
            owner.id,
            timezone_name="Asia/Dhaka",
            now=datetime.now(UTC),
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_postgres_integration_authenticated_api_returns_structured_insight(weekly_db):
    db, owner, _, _, _ = weekly_db

    async def current_user():
        return owner

    async def current_db():
        yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/ai/insights/weekly-medication",
                params={"timezone_name": "Asia/Dhaka"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["timezone_name"] == "Asia/Dhaka"
        assert body["recorded_facts"]["missed_doses"] == 1
        assert "unrecorded_doses_not_inferred" in body["observations"]
    finally:
        app.dependency_overrides.clear()
