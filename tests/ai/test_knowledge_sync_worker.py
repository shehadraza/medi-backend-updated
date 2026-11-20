from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.workers import knowledge_sync_worker as worker


class Result:
    def __init__(self, value): self.value = value
    def scalar_one_or_none(self): return self.value


class DB:
    def __init__(self, state=None): self.state, self.statements = state, []
    async def execute(self, stmt):
        self.statements.append(stmt)
        return Result("source-id")
    async def get(self, model, key): return self.state


class SessionContext:
    def __init__(self, db): self.db = db
    async def __aenter__(self): return self.db
    async def __aexit__(self, *args): return False


class EmptySourceResult:
    def scalar_one_or_none(self): return None


class EmptySourceDB:
    async def execute(self, statement): return EmptySourceResult()


@pytest.mark.asyncio
async def test_worker_is_disabled_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "AI_KNOWLEDGE_SYNC_ENABLED", False)
    assert await worker.run_sync_cycle() is False


@pytest.mark.asyncio
async def test_worker_respects_next_sync_and_uses_backoff_after_failure(monkeypatch, caplog):
    state = SimpleNamespace(next_sync_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    db = DB(state)
    monkeypatch.setattr(settings, "AI_KNOWLEDGE_SYNC_ENABLED", True)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: SessionContext(db))
    async def forbidden(*args, **kwargs): raise AssertionError("not due")
    monkeypatch.setattr(worker, "sync_medlineplus", forbidden)
    assert await worker.run_sync_cycle() is False
    delay = await worker.seconds_until_next_sync()
    assert 0 < delay <= 600


@pytest.mark.asyncio
async def test_worker_sanitizes_external_sync_failures(monkeypatch, caplog):
    state = SimpleNamespace(next_sync_at=None)
    monkeypatch.setattr(settings, "AI_KNOWLEDGE_SYNC_ENABLED", True)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: SessionContext(DB(state)))
    async def fail(*args, **kwargs): raise RuntimeError("private source response and credentials")
    monkeypatch.setattr(worker, "sync_medlineplus", fail)
    assert await worker.run_sync_cycle() is False
    assert "private source response" not in caplog.text


@pytest.mark.asyncio
async def test_one_source_failure_does_not_prevent_other_source_sync(monkeypatch, caplog):
    attempts = []
    monkeypatch.setattr(settings, "AI_KNOWLEDGE_SYNC_ENABLED", True)
    from types import SimpleNamespace
    monkeypatch.setattr(worker, "SOURCE_ADAPTERS", (
        SimpleNamespace(key="medlineplus", display_name="MedlinePlus", source_url="https://source-one.example", acquisition_enabled=True),
        SimpleNamespace(key="pubmed", display_name="PubMed", source_url="https://source-two.example", acquisition_enabled=True),
    ))
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: SessionContext(EmptySourceDB()))

    async def fail_medline(db):
        attempts.append("medlineplus")
        raise RuntimeError("private upstream response")

    async def sync_pubmed(db):
        attempts.append("pubmed")
        return {"seen": 1, "created": 1, "unchanged": 0, "metadata_updated": 0, "out_of_order": 0}

    monkeypatch.setattr(worker, "sync_medlineplus", fail_medline)
    monkeypatch.setattr(worker, "sync_pubmed", sync_pubmed)
    assert await worker.run_sync_cycle() is True
    assert attempts == ["medlineplus", "pubmed"]
    assert "private upstream response" not in caplog.text


@pytest.mark.asyncio
async def test_worker_keeps_medlineplus_running_and_skips_pubmed_even_when_email_is_set(monkeypatch):
    monkeypatch.setattr(settings, "AI_KNOWLEDGE_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "AI_NCBI_CONTACT_EMAIL", "qa@example.org")
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: SessionContext(DB()))
    seen = []

    async def medline(db):
        seen.append("medlineplus")
        return {"seen": 1, "created": 1, "unchanged": 0, "metadata_updated": 0, "out_of_order": 0}

    async def forbidden_pubmed(db):
        raise AssertionError("hard-coded source policy must not enable PubMed")

    monkeypatch.setattr(worker, "sync_medlineplus", medline)
    monkeypatch.setattr(worker, "sync_pubmed", forbidden_pubmed)
    assert await worker.run_sync_cycle() is True
    assert seen == ["medlineplus"]
