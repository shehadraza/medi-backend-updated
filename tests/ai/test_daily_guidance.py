from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.ai import service


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1


class FakeProvider:
    def __init__(self, available=True):
        self.available = available
        self.messages = None

    async def is_available(self):
        return self.available

    async def generate(self, messages, max_tokens):
        self.messages = messages
        return SimpleNamespace(done=True, content="Safe general wellness guidance.")


def setup_guidance(monkeypatch, consent=True, revoke=False, provider=None):
    db = FakeDB()
    provider = provider or FakeProvider()
    consent_calls = iter([consent, False] if revoke and consent else [consent])

    async def allow_rate_limit(user_id):
        return None

    async def consent_status(db, user_id):
        return next(consent_calls, consent)

    async def personal_context(db, user_id, query):
        return {
            "personalization_used": True,
            "context": {"private_test_marker": "PRIVATE_HEALTH_CONTEXT"},
        }

    async def retrieve(db, query, limit):
        return []

    monkeypatch.setattr(service.rate_limiter, "check", allow_rate_limit)
    monkeypatch.setattr(service, "get_personalization_status", consent_status)
    monkeypatch.setattr(service, "build_personal_context", personal_context)
    monkeypatch.setattr(service, "retrieve_chunks", retrieve)
    monkeypatch.setattr(service, "sanitize_retrieved_chunks", lambda x: x)
    monkeypatch.setattr(service, "filter_user_facing_sources", lambda x: x)
    monkeypatch.setattr(
        service, "_reference_messages",
        lambda context, retrieved, extra: (
            ["PRIVATE_HEALTH_CONTEXT"] if context else []
        ),
    )
    monkeypatch.setattr(
        service, "preflight_safety",
        lambda *a, **k: SimpleNamespace(response=None, indicators=[]),
    )
    monkeypatch.setattr(
        service, "validate_response",
        lambda question, answer, **kwargs: (answer, []),
    )
    monkeypatch.setattr(
        service, "validate_claims",
        lambda answer, evidence, **kwargs: SimpleNamespace(
            response=answer,
            citations=[],
            claims=[],
            supported=True,
        ),
    )
    monkeypatch.setattr(service, "rag_passages", lambda x: [])
    monkeypatch.setattr(service, "get_llm_provider", lambda: provider)

    return db, provider


@pytest.mark.asyncio
async def test_consent_off_does_not_load_personal_context(monkeypatch):
    db, provider = setup_guidance(monkeypatch, consent=False)

    result = await service.daily_guidance(db, "user-1")

    assert result["personalization_used"] is False
    assert "PRIVATE_HEALTH_CONTEXT" not in str(provider.messages)
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_consent_on_uses_authorized_personal_context(monkeypatch):
    db, provider = setup_guidance(monkeypatch, consent=True)

    result = await service.daily_guidance(db, "user-1")

    assert result["personalization_used"] is True
    assert "PRIVATE_HEALTH_CONTEXT" in str(provider.messages)
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_revoked_consent_removes_context_before_provider(monkeypatch):
    db, provider = setup_guidance(
        monkeypatch, consent=True, revoke=True
    )

    result = await service.daily_guidance(db, "user-1")

    assert result["personalization_used"] is False
    assert "PRIVATE_HEALTH_CONTEXT" not in str(provider.messages)
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_bangla_locale_is_passed_to_guidance_prompt(monkeypatch):
    db, provider = setup_guidance(monkeypatch, consent=False)

    await service.daily_guidance(db, "user-1", locale="bn")

    assert any(
        "Bengali" in getattr(message, "content", "")
        for message in provider.messages
    )


@pytest.mark.asyncio
async def test_provider_unavailable_returns_503(monkeypatch):
    provider = FakeProvider(available=False)
    db, _ = setup_guidance(
        monkeypatch, consent=False, provider=provider
    )

    with pytest.raises(HTTPException) as exc:
        await service.daily_guidance(db, "user-1")

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_missing_user_returns_401(monkeypatch):
    db = FakeDB()

    with pytest.raises(HTTPException) as exc:
        await service.daily_guidance(db, "")

    assert exc.value.status_code == 401
