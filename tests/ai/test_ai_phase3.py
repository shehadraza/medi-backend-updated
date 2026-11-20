import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.ai import AIMessage, AIConversation
from app.modules.ai import context_service, service
from app.modules.ai.providers.base import ChatMessage, LLMProviderError, LLMResponse
from app.modules.ai.rate_limit import InMemoryRateLimiter, RateLimitExceeded
from app.modules.ai.rag.citations import Citation
from app.modules.ai.rag.retrieval import RetrievedChunk
from app.modules.ai.safety import preflight_safety, validate_response
from app.modules.ai.schemas import AIRequest


class Result:
    def __init__(self, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, results=()):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.committed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else Result()

    def add(self, item):
        self.added.append(item)

    def add_all(self, items):
        self.added.extend(items)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None

    async def delete(self, item):
        return None


@pytest.mark.asyncio
async def test_consent_false_never_decrypts_or_queries_personal_records(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("profile decryption must not occur without consent")

    monkeypatch.setattr(context_service, "get_health_profile", forbidden)
    db = FakeDB([Result(scalar=False)])
    result = await context_service.build_personal_context(db, "owner-id", "my allergies")
    assert result == {"personalization_used": False, "context": {}}
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_missing_health_profile_is_generic_only(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("missing profile must not be decrypted")

    monkeypatch.setattr(context_service, "get_health_profile", forbidden)
    db = FakeDB([Result(scalar=None)])
    result = await context_service.build_personal_context(db, "owner-id", "sleep advice")
    assert result["personalization_used"] is False
    assert result["context"] == {}
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_consent_true_reads_only_allowlisted_profile_context(monkeypatch):
    seen = []

    async def read_profile(db, user_id):
        seen.append(user_id)
        return {
            "health_conditions": ["asthma"],
            "allergies": ["pollen"],
            "additional_notes": "unrelated private note",
            "sleep_hours": 6,
        }

    monkeypatch.setattr(context_service, "get_health_profile", read_profile)
    db = FakeDB([Result(scalar=True)])
    result = await context_service.build_personal_context(db, "owner-id", "my allergies")
    assert seen == ["owner-id"]
    assert result["personalization_used"] is True
    assert result["context"]["profile"] == {"health_conditions": ["asthma"], "allergies": ["pollen"]}
    assert "additional_notes" not in str(result)


@pytest.mark.asyncio
async def test_unconfirmed_prescription_ocr_is_never_loaded(monkeypatch):
    async def read_profile(db, user_id):
        return {"allergies": []}

    monkeypatch.setattr(context_service, "get_health_profile", read_profile)
    db = FakeDB([Result(scalar=True), Result(rows=[]), Result(rows=[])])
    result = await context_service.build_personal_context(db, "owner-id", "my medicine")
    assert result["context"]["unverified_prescription_data_used"] is False
    prescription_query = str(db.statements[2])
    assert "confirmed_at" in prescription_query
    assert "verification_status" in prescription_query


@pytest.mark.asyncio
async def test_cross_user_conversation_access_is_not_found():
    db = FakeDB([Result(scalar=None)])
    with pytest.raises(HTTPException) as error:
        await service.get_conversation(db, "owner-a", "conversation-b", limit=10, offset=0)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_conversation_history_is_not_loaded_without_explicit_request_opt_in(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("history must not be decrypted without opt-in")

    monkeypatch.setattr(service, "decrypt_message_content", forbidden)
    db = FakeDB()
    result = await service._load_conversation_history(
        db, "owner-id", "conversation-id", enabled=False,
    )
    assert result == []
    assert db.statements == []
    assert AIRequest(message="Hello").use_conversation_history is False
    assert AIRequest(message="Hello", use_conversation_history=True).use_conversation_history is True


@pytest.mark.asyncio
async def test_conversation_history_is_owner_scoped_and_decrypted_only_after_opt_in(monkeypatch):
    record = SimpleNamespace(role="user", user_id="owner-id", conversation_id="conversation-id")
    monkeypatch.setattr(service, "decrypt_message_content", lambda row: "prior user question")
    db = FakeDB([Result(rows=[record])])
    history = await service._load_conversation_history(
        db, "owner-id", "conversation-id", enabled=True,
    )
    assert [message.content for message in history] == ["prior user question"]
    statement = str(db.statements[0])
    assert "ai_messages.user_id" in statement
    assert "ai_messages.conversation_id" in statement


@pytest.mark.asyncio
async def test_conversation_deletion_remains_owner_scoped_and_cascades_via_model_delete():
    conversation = AIConversation(id="conversation-id", user_id="owner-id")

    class DeleteDB(FakeDB):
        def __init__(self, results):
            super().__init__(results)
            self.deleted = []

        async def delete(self, item):
            self.deleted.append(item)

    owner_db = DeleteDB([Result(scalar=conversation)])
    await service.delete_conversation(owner_db, "owner-id", "conversation-id")
    assert owner_db.deleted == [conversation]
    assert owner_db.committed

    other_db = DeleteDB([Result(scalar=None)])
    with pytest.raises(HTTPException) as error:
        await service.delete_conversation(other_db, "other-user", "conversation-id")
    assert error.value.status_code == 404
    assert other_db.deleted == []


@pytest.mark.asyncio
async def test_cross_user_feedback_message_access_is_not_found():
    db = FakeDB([Result(scalar=None)])
    with pytest.raises(HTTPException) as error:
        await service.submit_feedback(db, "owner-a", "message-b", "helpful", None)
    assert error.value.status_code == 404


def test_emergency_guidance_is_deterministic_and_localized():
    english = preflight_safety("I have chest pain and can't breathe")
    bangla = preflight_safety("আমার বুকে ব্যথা ও শ্বাসকষ্ট", locale="bn")
    assert "emergency" in english.indicators
    assert "emergency services" in english.response
    assert "জরুরি" in bangla.response


def test_dose_change_request_is_refused_without_llm():
    decision = preflight_safety("Should I double my medication dose?")
    assert decision.response
    assert "cannot recommend changing" in decision.response
    assert "medication_change_refused" in decision.indicators


def test_unverified_or_conflicting_dose_claim_is_blocked():
    response, indicators = validate_response(
        "What dose should I take?",
        "Take 500 mg twice daily.",
        personal_context={},
        evidence_available=True,
    )
    assert "cannot verify" in response
    assert "prescription_dose_unverified" in indicators


def test_generated_diagnosis_and_unverified_dose_claims_are_blocked():
    diagnosis, diagnosis_flags = validate_response(
        "What might cause this?", "You may have asthma.", personal_context={}, evidence_available=True,
    )
    dose, dose_flags = validate_response(
        "Tell me about this medicine.", "You should take 500 mg daily.", personal_context={}, evidence_available=True,
    )
    assert "cannot diagnose" in diagnosis
    assert "diagnosis_blocked" in diagnosis_flags
    assert "cannot recommend a medicine or dose" in dose
    assert "prescription_or_dose_blocked" in dose_flags


def test_confirmed_dose_answer_requires_one_named_record():
    from app.modules.ai.safety import confirmed_prescription_answer

    context = {
        "confirmed_prescription_instructions": [{
            "verification": "user_confirmed_prescription",
            "instructions": {
                "medicine_name": "ExampleMed",
                "dose": "1 tablet",
                "frequency": "once daily",
                "duration": "5 days",
            },
        }],
    }
    answer = confirmed_prescription_answer("What dose of ExampleMed?", context, locale="en")
    assert answer and "1 tablet" in answer[0]
    assert confirmed_prescription_answer("What dose should I take?", context, locale="en")[1] == [
        "prescription_dose_unverified", "professional_care",
    ]


@pytest.mark.parametrize("question,field", [
    ("When should I take ExampleMed?", "timing"),
    ("Should I take ExampleMed with food?", "food_instruction"),
])
def test_confirmed_timing_and_food_instructions_are_exact_and_missing_is_explicit(question, field):
    from app.modules.ai.safety import confirmed_prescription_answer

    context = {"confirmed_prescription_instructions": [{"instructions": {
        "medicine_name": "ExampleMed", "dose": "1 tablet", "frequency": "daily",
        "duration": "5 days", "timing": "after breakfast", "food_instruction": "take with food",
    }}]}
    answer = confirmed_prescription_answer(question, context, locale="en")
    assert answer and context["confirmed_prescription_instructions"][0]["instructions"][field] in answer[0]
    context["confirmed_prescription_instructions"][0]["instructions"].pop(field)
    missing = confirmed_prescription_answer(question, context, locale="en")
    assert missing and "not recorded" in missing[0]


@pytest.mark.parametrize("question", ["কখন ExampleMed খাব?", "ExampleMed কি খাবারের সাথে খাব?"])
def test_bangla_prescription_timing_and_food_questions_are_deterministic(question):
    from app.modules.ai.safety import confirmed_prescription_answer

    context = {"confirmed_prescription_instructions": [{"instructions": {
        "medicine_name": "ExampleMed", "timing": "after breakfast", "food_instruction": "with food",
    }}]}
    answer = confirmed_prescription_answer(question, context, locale="bn")
    assert answer and "after breakfast" in answer[0] or answer and "with food" in answer[0]


@pytest.mark.asyncio
async def test_prescription_instruction_answer_bypasses_conflicting_rag(monkeypatch):
    from app.core.config import settings
    from app.modules.ai.message_crypto import decrypt_message_content

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=")
    monkeypatch.setattr(service.rate_limiter, "check", lambda key: asyncio.sleep(0))
    monkeypatch.setattr(service, "get_personalization_status", lambda *a: asyncio.sleep(0, result=True))
    monkeypatch.setattr(service, "build_personal_context", lambda *a: asyncio.sleep(0, result={
        "personalization_used": True,
        "context": {"confirmed_prescription_instructions": [{"instructions": {
            "medicine_name": "ExampleMed", "food_instruction": "take with food",
        }}]},
    }))
    async def forbidden(*args, **kwargs): raise AssertionError("conflicting RAG must not run for this question")
    monkeypatch.setattr(service, "retrieve_chunks", forbidden)
    db = FakeDB()
    answer = await service.chat(db, "owner-id", AIRequest(message="Should I take ExampleMed with food?"))
    assert "take with food" in answer["response"]
    assistant = next(row for row in db.added if isinstance(row, AIMessage) and row.role == "assistant")
    assert decrypt_message_content(assistant) == answer["response"]


def test_reminder_answer_quotes_settings_and_labels_them_not_prescription():
    from app.modules.ai.safety import user_reminder_answer

    result = user_reminder_answer(
        "What is my reminder schedule?",
        {"reminder_schedules": [{
            "medicine_name": "ExampleMed",
            "reminder_schedule": {"reminder_times": ["08:00"], "timezone_name": "Asia/Dhaka"},
            "next_dose_at": None,
        }]},
        locale="en",
    )
    assert result and "08:00" in result[0]
    assert "not a prescription instruction" in result[0]


def test_unverified_ocr_is_explicitly_excluded_from_prompt_policy():
    from app.modules.ai.safety import system_instructions

    prompt = system_instructions(locale="en", personal_context={"unverified_prescription_data_used": False}, evidence_available=False)
    assert "Unconfirmed OCR is not evidence" in prompt
    assert "never infer dose" in prompt


def test_request_accepts_bangla_and_english_and_rejects_other_locale():
    assert AIRequest(message="Hello", locale="en").locale == "en"
    assert AIRequest(message="হ্যালো", locale="bn").locale == "bn"
    with pytest.raises(ValueError):
        AIRequest(message="Hola", locale="es")


@pytest.mark.asyncio
async def test_rate_limiter_enforces_window():
    limiter = InMemoryRateLimiter(limit=1, window_seconds=60)
    await limiter.check("user-1")
    with pytest.raises(RateLimitExceeded):
        await limiter.check("user-1")
    await limiter.check("user-2")


@pytest.mark.asyncio
async def test_provider_unavailable_returns_safe_error_without_persisting(monkeypatch):
    class OfflineProvider:
        async def is_available(self):
            return False

        async def generate(self, *args, **kwargs):
            raise AssertionError("unavailable provider must not generate")

    monkeypatch.setattr(service, "get_llm_provider", lambda: OfflineProvider())
    monkeypatch.setattr(service.rate_limiter, "check", lambda key: asyncio.sleep(0))
    db = FakeDB([Result(scalar=False), Result(rows=[])])
    with pytest.raises(HTTPException) as error:
        await service.chat(db, "owner-id", AIRequest(message="General question"))
    assert error.value.status_code == 503
    assert "temporarily unavailable" in error.value.detail
    assert db.added == []


@pytest.mark.asyncio
async def test_provider_timeout_is_sanitized(monkeypatch):
    import httpx
    from app.modules.ai.providers.ollama import OllamaProvider

    class TimedOutClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs): raise httpx.ReadTimeout("private timeout detail")

    monkeypatch.setattr("app.modules.ai.providers.ollama.httpx.AsyncClient", TimedOutClient)
    provider = OllamaProvider(model="test-model", timeout=0.01)
    with pytest.raises(LLMProviderError, match="unavailable") as error:
        await provider.generate([ChatMessage("user", "test")])
    assert "private timeout detail" not in str(error.value)


@pytest.mark.asyncio
async def test_consent_revocation_drops_context_before_provider_call(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=")
    monkeypatch.setattr(service.rate_limiter, "check", lambda key: asyncio.sleep(0))
    statuses = iter([True, False])
    monkeypatch.setattr(service, "get_personalization_status", lambda *args: asyncio.sleep(0, result=next(statuses)))
    monkeypatch.setattr(context_service, "get_health_profile", lambda *args: asyncio.sleep(0, result={"health_conditions": ["PRIVATE_CONDITION"]}))
    monkeypatch.setattr(service, "retrieve_chunks", lambda *args, **kwargs: asyncio.sleep(0, result=[]))

    class OnlineProvider:
        prompt = None
        async def is_available(self): return True
        async def generate(self, messages, **kwargs):
            self.prompt = "\n".join(message.content for message in messages)
            return LLMResponse("General information.", "mock-model")

    provider = OnlineProvider()
    monkeypatch.setattr(service, "get_llm_provider", lambda: provider)
    db = FakeDB([Result(scalar=True)])
    answer = await service.chat(db, "owner-id", AIRequest(message="What does my sleep profile say?"))
    assert answer["personalization_used"] is False
    assert "PRIVATE_CONDITION" not in provider.prompt


@pytest.mark.asyncio
async def test_confirmed_prescription_instructions_precede_and_ignore_general_rag(monkeypatch):
    monkeypatch.setattr(service.rate_limiter, "check", lambda key: asyncio.sleep(0))
    monkeypatch.setattr(service, "get_personalization_status", lambda *args: asyncio.sleep(0, result=True))
    monkeypatch.setattr(service, "build_personal_context", lambda *args: asyncio.sleep(0, result={
        "personalization_used": True,
        "context": {"confirmed_prescription_instructions": [{
            "instructions": {
                "medicine_name": "ExampleMed",
                "dose": "1 tablet",
                "frequency": "once daily",
                "duration": None,
                "timing": "morning",
                "food_instruction": "with food",
            },
        }]},
    }))

    async def forbidden_rag(*args, **kwargs):
        raise AssertionError("prescription answer must not be generated from general RAG")

    monkeypatch.setattr(service, "retrieve_chunks", forbidden_rag)
    async def persist(*args, **kwargs):
        return {"response": args[5], "citations": [], "safety_indicators": args[9]}
    monkeypatch.setattr(service, "_persist_response", persist)

    result = await service.chat(
        FakeDB([Result(scalar=True)]),
        "owner-id",
        AIRequest(message="When should I take ExampleMed?"),
    )
    assert "timing: morning" in result["response"]
    assert result["citations"] == []


@pytest.mark.asyncio
async def test_chat_persists_only_encrypted_messages_and_real_citations(monkeypatch):
    from app.core.config import settings
    from app.modules.ai.message_crypto import decrypt_message_content

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=")
    monkeypatch.setattr(service.rate_limiter, "check", lambda key: asyncio.sleep(0))
    citation = Citation(
        source_id="source-1", source_name="Approved source", source_url="https://medlineplus.gov/topic.html",
        source_reference="section 1", document_id="doc-1", document_title="Guideline",
        document_version=1, chunk_id="chunk-1", trust_classification="approved_source_registry",
    )

    class OnlineProvider:
        async def is_available(self): return True
        async def generate(self, *args, **kwargs): return LLMResponse("Headache is associated with dehydration.", "mock-model")

    monkeypatch.setattr(service, "get_llm_provider", lambda: OnlineProvider())
    monkeypatch.setattr(service, "retrieve_chunks", lambda *args, **kwargs: asyncio.sleep(0, result=[RetrievedChunk("Headache is associated with dehydration.", 0.8, citation)]))
    db = FakeDB([Result(scalar=False)])
    answer = await service.chat(db, "owner-id", AIRequest(message="What is general health information?"))
    messages = [item for item in db.added if isinstance(item, AIMessage)]
    assert db.committed
    assert len(messages) == 2
    assert all(not hasattr(item, "content") for item in messages)
    assert decrypt_message_content(messages[0]) == "What is general health information?"
    expected_citation = {**citation.as_dict(), "claim_ids": ["c1"]}
    assert answer["citations"] == [expected_citation]
    assert messages[1].citations == [expected_citation]
    assert answer["claim_evidence"][0]["supported"] is True
    assert answer["claim_evidence"][0]["citation_ids"] == ["chunk-1"]


def test_no_evidence_does_not_create_or_fabricate_citations():
    result, indicators = validate_response(
        "General question", "General information.", personal_context={}, evidence_available=False,
    )
    assert "trusted medical source" in result
    assert indicators == ["insufficient_evidence"]


@pytest.mark.asyncio
async def test_ai_context_route_requires_authentication():
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ai/context")
    assert response.status_code == 401


def test_phase3_routes_are_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert {
        "/ai/chat",
        "/ai/context",
        "/ai/conversations",
        "/ai/conversations/{conversation_id}",
        "/ai/messages/{message_id}/feedback",
    }.issubset(paths)
