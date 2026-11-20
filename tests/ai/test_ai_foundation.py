import base64
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.models.ai import KnowledgeChunk
from app.modules.ai.embeddings.base import EmbeddingProviderError
from app.modules.ai.embeddings.ollama import OllamaEmbeddingProvider
from app.modules.ai.message_crypto import (
    decrypt_conversation_title,
    decrypt_message_content,
    encrypt_conversation_title,
    encrypt_message_content,
    message_aad,
    new_encrypted_message,
)
from app.modules.ai.providers.base import ChatMessage, LLMProviderError
from app.modules.ai.providers.ollama import OllamaProvider
from app.modules.ai.rag.chunking import chunk_text, normalize_text
from app.modules.ai.rag.extraction import DocumentExtractionError, extract_document_text
from app.modules.ai.rag.ingestion import ingest_document
from app.modules.ai.rag.retrieval import retrieve_chunks


def test_normalization_and_overlapping_chunks():
    assert normalize_text("  First\tline\r\n\r\n\r\nSecond  ") == "First line\n\nSecond"
    chunks = chunk_text("one two three four five six seven", chunk_size=15, overlap=4)
    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)
    assert "four" in chunks[0] + chunks[1]


def test_chunking_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_size=10, overlap=10)


def test_extract_text_and_reject_unknown_format():
    assert extract_document_text(b"MEDI reference", "guide.txt") == "MEDI reference"
    with pytest.raises(DocumentExtractionError):
        extract_document_text(b"data", "guide.docx")


@pytest.mark.asyncio
async def test_ollama_unavailable_when_model_not_configured():
    provider = OllamaProvider(model="")
    assert await provider.is_available() is False
    with pytest.raises(LLMProviderError):
        await provider.generate([ChatMessage("user", "Hello")])


@pytest.mark.asyncio
async def test_ollama_availability_failure_is_graceful(monkeypatch):
    import httpx

    class BrokenClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): raise httpx.ConnectError("connection unavailable")

    monkeypatch.setattr("app.modules.ai.providers.ollama.httpx.AsyncClient", BrokenClient)
    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="local-model")
    assert await provider.is_available() is False


@pytest.mark.asyncio
async def test_ollama_generation_failure_is_sanitized(monkeypatch):
    import httpx

    class BrokenClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs): raise httpx.ConnectError("secret transport detail")

    monkeypatch.setattr("app.modules.ai.providers.ollama.httpx.AsyncClient", BrokenClient)
    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="local-model")
    with pytest.raises(LLMProviderError, match="unavailable") as error:
        await provider.generate([ChatMessage("user", "Hello")])
    assert "secret transport detail" not in str(error.value)


@pytest.mark.asyncio
async def test_embedding_requires_configured_model():
    provider = OllamaEmbeddingProvider(model="")
    assert await provider.is_available() is False
    with pytest.raises(Exception, match="not configured"):
        await provider.embed(["reference text"])


@pytest.mark.asyncio
async def test_embedding_transport_failure_is_sanitized(monkeypatch):
    import httpx

    class BrokenClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs): raise httpx.ConnectError("private transport detail")

    monkeypatch.setattr("app.modules.ai.embeddings.ollama.httpx.AsyncClient", BrokenClient)
    provider = OllamaEmbeddingProvider(model="local-embedding")
    with pytest.raises(EmbeddingProviderError, match="unavailable") as error:
        await provider.embed(["public text"])
    assert "private transport detail" not in str(error.value)


def test_message_encryption_is_user_and_message_scoped(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    ciphertext = encrypt_message_content("user-1", "conv-1", "msg-1", "private health question")
    assert "private health question" not in ciphertext
    record = SimpleNamespace(
        user_id="user-1", conversation_id="conv-1", id="msg-1", encrypted_content=ciphertext,
    )
    assert decrypt_message_content(record) == "private health question"
    with pytest.raises(Exception):
        decrypt_message_content(SimpleNamespace(**{**record.__dict__, "user_id": "user-2"}))
    assert message_aad("user-1", "conv-1", "msg-1") != message_aad("user-2", "conv-1", "msg-1")


def test_message_factory_only_persists_ciphertext(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", base64.b64encode(b"y" * 32).decode())
    record = new_encrypted_message("user-1", "conv-1", "user", "private question")
    assert not hasattr(record, "content")
    assert record.encrypted_content != "private question"
    assert decrypt_message_content(record) == "private question"


def test_conversation_title_encryption_is_user_scoped(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", base64.b64encode(b"z" * 32).decode())
    ciphertext = encrypt_conversation_title("user-1", "conv-1", "Private title")
    assert "Private title" not in ciphertext
    assert decrypt_conversation_title("user-1", "conv-1", ciphertext) == "Private title"
    with pytest.raises(Exception):
        decrypt_conversation_title("user-2", "conv-1", ciphertext)


class FakeDB:
    def __init__(self, rows=()):
        self.rows = rows
        self.added = []
        self.statements = []

    async def execute(self, statement):
        self.statement = statement
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_ingestion_persists_chunks_without_publishing(monkeypatch):
    monkeypatch.setattr(settings, "AI_RAG_CHUNK_SIZE", 64)
    monkeypatch.setattr(settings, "AI_RAG_CHUNK_OVERLAP", 8)
    db = FakeDB()
    document = SimpleNamespace(id="doc-1", language="en", version=1, status="draft")
    count = await ingest_document(db, document, b"Trusted reference text about general health.", "source.txt")
    assert count == 1
    assert document.status == "ready"
    assert len(document.content_hash) == 64
    assert len(db.added) == 1
    assert db.added[0].embedding is None


@pytest.mark.asyncio
async def test_retrieval_returns_only_persisted_source_citations():
    chunk = SimpleNamespace(id="chunk-1", text="Reference passage")
    document = SimpleNamespace(id="doc-1", title="Guideline", version=2)
    source = SimpleNamespace(id="source-1", name="Health authority", source_url="https://example.invalid/g", source_reference="section 2")
    db = FakeDB([(chunk, document, source, 0.75)])
    retrieved = await retrieve_chunks(db, "health guidance", limit=3)
    compiled_statements = [
        statement.compile(dialect=postgresql.dialect())
        for statement in db.statements
    ]
    sql = "\n".join(str(statement) for statement in compiled_statements)
    params = [
        value
        for statement in compiled_statements
        for value in statement.params.values()
    ]

    assert "review_status" in sql and "status" in sql
    assert "approved" in params
    assert "published" in params
    assert retrieved[0].citation.source_name == "Health authority"
    assert retrieved[0].citation.chunk_id == "chunk-1"
    assert retrieved[0].score == pytest.approx(1 / 61)


def test_chunk_metadata_has_full_text_index_in_model_metadata():
    indexes = {index.name for index in KnowledgeChunk.__table__.indexes}
    assert "ix_ai_knowledge_chunks_fts" in indexes

