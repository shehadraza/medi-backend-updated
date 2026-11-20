import hashlib
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai import KnowledgeChunk, KnowledgeDocument
from app.modules.ai.embeddings.base import EmbeddingProvider
from app.modules.ai.rag.chunking import chunk_text, normalize_text
from app.modules.ai.rag.extraction import extract_document_text


async def ingest_document(
    db: AsyncSession,
    document: KnowledgeDocument,
    content: bytes,
    filename: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> int:
    """Extract and persist draft chunks. This function never publishes a document."""
    document.status = "processing"
    document.error_code = None
    try:
        normalized = normalize_text(extract_document_text(content, filename))
        if not normalized:
            raise ValueError("Document contains no extractable text.")
        chunks = chunk_text(
            normalized,
            chunk_size=settings.AI_RAG_CHUNK_SIZE,
            overlap=settings.AI_RAG_CHUNK_OVERLAP,
        )
        vectors: list[list[float] | None] = [None] * len(chunks)
        if embedding_provider and chunks:
            vectors = await embedding_provider.embed(chunks)
            if len(vectors) != len(chunks):
                raise ValueError("Embedding provider returned an invalid batch size.")
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
        document.content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db.add(KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                text=chunk,
                metadata_json={"language": document.language, "version": document.version},
                embedding=vector,
                embedding_provider=embedding_provider.provider_name if vector is not None else None,
                embedding_model=embedding_provider.model_name if vector is not None else None,
            ))
        document.status = "ready"
        document.ingested_at = datetime.now(timezone.utc)
        await db.flush()
        return len(chunks)
    except Exception:
        document.status = "failed"
        document.error_code = "ingestion_failed"
        await db.flush()
        raise
