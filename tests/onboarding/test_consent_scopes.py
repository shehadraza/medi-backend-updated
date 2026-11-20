from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.health_profile import HealthProfile
from app.modules.ai import context_service
from app.modules.notifications import routes as notification_routes
from app.modules.notifications.schemas import HealthReminderRequest
from app.modules.notifications.service import enqueue_dose_notifications
from app.modules.onboarding import service as onboarding_service
from app.modules.onboarding.schemas import ProactiveConsentRequest


class Result:
    def __init__(self, *, scalar=None, row=None, rows=()):
        self.scalar = scalar
        self.row = row
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar

    def one_or_none(self):
        return self.row

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class FakeDB:
    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else Result()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def make_profile(**overrides):
    values = {
        "user_id": "owner-1",
        "ai_personalization_consent": False,
        "ai_personalization_consent_at": None,
        "proactive_health_analysis_consent": False,
        "proactive_health_analysis_consent_at": None,
        "proactive_wellness_notifications_consent": False,
        "proactive_wellness_notifications_consent_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_proactive_consent_columns_default_false_and_timestamps_are_nullable():
    for name in (
        "proactive_health_analysis_consent",
        "proactive_wellness_notifications_consent",
    ):
        column = HealthProfile.__table__.c[name]
        assert column.default.arg is False
        assert str(column.server_default.arg).lower() == "false"
        assert not column.nullable
    assert HealthProfile.__table__.c.proactive_health_analysis_consent_at.nullable
    assert HealthProfile.__table__.c.proactive_wellness_notifications_consent_at.nullable


def test_proactive_consent_request_is_strict():
    with pytest.raises(ValueError):
        ProactiveConsentRequest.model_validate({"enabled": True, "user_id": "other"})


@pytest.mark.asyncio
async def test_consent_status_reads_only_owner_scoped_consent_columns():
    now = datetime.now(timezone.utc)
    db = FakeDB([Result(row=(True, now, False, None, True, now))])

    result = await onboarding_service.get_consent_status(db, "owner-1")

    sql = str(db.statements[0])
    assert "health_profiles.user_id" in sql
    assert "encrypted_data" not in sql
    assert result == {
        "ai_personalization_consent": True,
        "ai_personalization_consent_at": now,
        "proactive_health_analysis_consent": False,
        "proactive_health_analysis_consent_at": None,
        "proactive_wellness_notifications_consent": True,
        "proactive_wellness_notifications_consent_at": now,
    }


@pytest.mark.asyncio
async def test_proactive_scopes_change_independently_without_changing_interactive_consent():
    profile = make_profile(ai_personalization_consent=True)
    analysis_db = FakeDB([Result(scalar=profile)])
    await onboarding_service.update_proactive_consent(
        analysis_db, "owner-1", scope="health_analysis", enabled=True,
    )
    assert profile.proactive_health_analysis_consent is True
    assert profile.proactive_health_analysis_consent_at is not None
    assert profile.proactive_wellness_notifications_consent is False
    assert profile.ai_personalization_consent is True

    notification_db = FakeDB([Result(scalar=profile)])
    await onboarding_service.update_proactive_consent(
        notification_db, "owner-1", scope="wellness_notifications", enabled=True,
    )
    assert profile.proactive_health_analysis_consent is True
    assert profile.proactive_wellness_notifications_consent is True
    assert profile.ai_personalization_consent is True

    await onboarding_service.update_proactive_consent(
        FakeDB([Result(scalar=profile)]),
        "owner-1",
        scope="health_analysis",
        enabled=False,
    )
    assert profile.proactive_health_analysis_consent is False
    assert profile.proactive_wellness_notifications_consent is True
    assert profile.ai_personalization_consent is True


@pytest.mark.asyncio
async def test_interactive_consent_update_keeps_existing_behavior():
    profile = make_profile()

    class InteractiveDB(FakeDB):
        async def execute(self, statement):
            self.statements.append(statement)
            return Result(scalar=profile)

    await onboarding_service.update_ai_personalization_consent(
        InteractiveDB(), "owner-1", True,
    )
    assert profile.ai_personalization_consent is True
    assert profile.ai_personalization_consent_at is not None
    assert profile.proactive_health_analysis_consent is False
    assert profile.proactive_wellness_notifications_consent is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "consent_row", "purpose_allowed", "personal_allowed"),
    [
        ("proactive_analysis", (True, False), False, False),
        ("proactive_analysis", (False, True), False, False),
        ("wellness_notification", (False, True), True, False),
        ("wellness_notification", (True, False), False, False),
    ],
)
async def test_missing_or_partial_consent_never_reads_personal_records(
    monkeypatch, purpose, consent_row, purpose_allowed, personal_allowed,
):
    async def forbidden(*args, **kwargs):
        raise AssertionError("personal records must not be decrypted without all relevant consent")

    monkeypatch.setattr(context_service, "get_health_profile", forbidden)
    db = FakeDB([Result(row=consent_row)])

    result = await context_service.build_personal_context(
        db, "owner-1", "sleep and medicine", purpose=purpose,
    )

    assert result["purpose_allowed"] is purpose_allowed
    assert result["personal_data_used"] is personal_allowed
    assert result["context"] == {}
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_proactive_context_requires_both_analysis_and_interactive_consent(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("revoked interactive consent must block context reads")

    monkeypatch.setattr(context_service, "get_health_profile", forbidden)
    db = FakeDB([Result(row=(False, True))])
    result = await context_service.build_personal_context(
        db, "owner-1", "weekly sleep summary", purpose="proactive_analysis",
    )
    assert result["purpose_allowed"] is False
    assert result["context"] == {}
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_interactive_profile_decryption_still_requires_existing_consent(monkeypatch):
    calls = []

    async def read_profile(*args):
        calls.append(True)
        return {"screen_time_hours": 8}

    monkeypatch.setattr(context_service, "get_health_profile", read_profile)
    denied = await context_service.build_personal_context(
        FakeDB([Result(scalar=False)]), "owner-1", "screen time",
    )
    assert denied == {"personalization_used": False, "context": {}}
    assert calls == []

    allowed = await context_service.build_personal_context(
        FakeDB([Result(scalar=True)]), "owner-1", "screen time",
    )
    assert allowed["context"]["profile"] == {"screen_time_hours": 8}
    assert calls == [True]


@pytest.mark.asyncio
async def test_existing_user_created_reminders_do_not_require_wellness_consent(monkeypatch):
    from app.modules.notifications import service as notification_service

    monkeypatch.setattr(notification_service, "encrypt_notification_payload", lambda *args: "ciphertext")
    now = datetime.now(timezone.utc)
    db = FakeDB([Result(rows=[SimpleNamespace(id="dose-1", scheduled_at=now)]), Result(scalar=None)])

    assert await enqueue_dose_notifications(db, "owner-1") == 1
    assert db.added[0].notification_type == "medication_reminder"
    assert db.added[0].channel == "in_app"
    assert all("health_profiles" not in str(statement) for statement in db.statements)


@pytest.mark.asyncio
async def test_existing_explicit_health_reminder_does_not_require_wellness_consent(monkeypatch):
    monkeypatch.setattr(notification_routes, "encrypt_notification_payload", lambda *args: "ciphertext")
    db = FakeDB([Result(scalar=None)])
    payload = HealthReminderRequest(
        message="Call my clinic",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=30),
        idempotency_key="clinic-followup-1",
    )
    result = await notification_routes.create_health_reminder(
        payload, current_user=SimpleNamespace(id="owner-1"), db=db,
    )
    assert result["notification_id"] == db.added[0].id
    assert db.added[0].user_id == "owner-1"
    assert db.added[0].channel == "in_app"


@pytest.mark.asyncio
async def test_consent_api_requires_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/onboarding/consent")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_consent_status_api_uses_authenticated_owner_and_never_accepts_user_id():
    user = SimpleNamespace(id="authenticated-owner")
    db = FakeDB([Result(row=(False, None, False, None, False, None))])

    async def override_user():
        return user

    async def override_db():
        yield db

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/onboarding/consent")
            invalid = await client.patch(
                "/onboarding/consent/proactive-health-analysis",
                json={"enabled": True, "user_id": "other-user"},
            )
        assert response.status_code == 200
        assert response.json()["proactive_health_analysis_consent"] is False
        assert invalid.status_code == 422
        assert "authenticated-owner" in str(db.statements[0].compile().params)
        assert "other-user" not in str(db.statements[0].compile().params)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_consent_api_updates_analysis_and_wellness_scopes_separately():
    user = SimpleNamespace(id="authenticated-owner")
    now = datetime.now(timezone.utc)
    profile = make_profile()
    db = FakeDB([
        Result(scalar=profile),
        Result(row=(False, None, True, now, False, None)),
        Result(scalar=profile),
        Result(row=(False, None, True, now, True, now)),
    ])

    async def override_user():
        return user

    async def override_db():
        yield db

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            analysis = await client.patch(
                "/onboarding/consent/proactive-health-analysis",
                json={"enabled": True},
            )
            notifications = await client.patch(
                "/onboarding/consent/proactive-wellness-notifications",
                json={"enabled": True},
            )
        assert analysis.status_code == 200
        assert analysis.json()["proactive_health_analysis_consent"] is True
        assert analysis.json()["proactive_wellness_notifications_consent"] is False
        assert notifications.status_code == 200
        assert notifications.json()["proactive_health_analysis_consent"] is True
        assert notifications.json()["proactive_wellness_notifications_consent"] is True
        assert all("authenticated-owner" in str(item.compile().params) for item in db.statements)
    finally:
        app.dependency_overrides.clear()
