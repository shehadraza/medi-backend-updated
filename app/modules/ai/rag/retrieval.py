
import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.modules.ai.embeddings.factory import get_embedding_provider
from app.modules.ai.rag.citations import Citation
from app.modules.ai.source_policy import (
    PUBMED_SOURCE_NAME,
    PUBMED_SOURCE_URL,
    PUBMED_USER_FACING_ENABLED,
)
from app.modules.ai.untrusted_data import safe_untrusted_text


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float
    citation: Citation


_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_BENGALI = re.compile(r"[\u0980-\u09ff]")
_STOP_WORDS = {
    "what", "are", "is", "the", "a", "an", "of", "for",
    "to", "in", "on", "common", "causes", "about", "with",
    "and", "how", "why",
}

_BILINGUAL_TERMS = (
    ("headache", "head ache", "headaches", "cephalalgia", "মাথাব্যথা", "মাথা ব্যথা"),
    ("fever", "pyrexia", "জ্বর"),
    ("diabetes", "high blood sugar", "high blood glucose", "ডায়াবেটিস", "বহুমূত্র"),
    ("hypertension", "high blood pressure", "উচ্চ রক্তচাপ"),
    ("asthma", "হাঁপানি", "শ্বাসকষ্ট"),
    ("heart disease", "হৃদরোগ", "হৃদ্‌রোগ"),
    ("medicine", "medication", "drug", "ওষুধ", "ঔষধ"),
    ("pregnancy", "গর্ভাবস্থা", "গর্ভধারণ"),
)


def expand_medical_query(query: str) -> str:
    tokens = [
        token.casefold()
        for token in _TOKEN.findall(query[:1000])
        if token.casefold() not in _STOP_WORDS
        and not _BENGALI.search(token)
    ]

    terms = list(tokens)
    normalized = query.casefold()

    if _BENGALI.search(normalized):
        terms.append(" ".join(normalized.split()))

    for aliases in _BILINGUAL_TERMS:
        if any(alias.casefold() in normalized for alias in aliases):
            terms.extend(alias.casefold() for alias in aliases)

    return " OR ".join(dict.fromkeys(terms) if terms else [])


def _cosine_similarity(a: list, b: list) -> float:
    if not isinstance(a, list) or not isinstance(b, list):
        return 0.0
    if not a or len(a) != len(b):
        return 0.0

    try:
        left = [float(x) for x in a]
        right = [float(x) for x in b]

        if not all(math.isfinite(x) for x in left + right):
            return 0.0

        dot = sum(x * y for x, y in zip(left, right))
        norm_a = math.sqrt(sum(x * x for x in left))
        norm_b = math.sqrt(sum(y * y for y in right))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _is_redundant(candidate: str, retained: list[str]) -> bool:
    candidate_terms = set(_TOKEN.findall(candidate.casefold()))
    if not candidate_terms:
        return True

    for text in retained:
        prior = set(_TOKEN.findall(text.casefold()))
        union = candidate_terms | prior
        if union and len(candidate_terms & prior) / len(union) >= 0.88:
            return True

    return False


def sanitize_retrieved_chunks(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    clean = []

    for item in chunks:
        citation = item.citation
        metadata = (
            citation.source_name,
            citation.source_url,
            citation.source_reference,
            citation.document_title,
        )

        if any(
            value is not None
            and safe_untrusted_text(str(value), limit=1000) is None
            for value in metadata
        ):
            continue

        text = safe_untrusted_text(item.text, limit=2500)
        if text is not None:
            clean.append(replace(item, text=text))

    return clean


def filter_user_facing_sources(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    if PUBMED_USER_FACING_ENABLED:
        return chunks

    filtered = []

    for item in chunks:
        try:
            host = urlparse(item.citation.source_url or "").hostname
        except ValueError:
            host = None

        if (
            item.citation.source_name == PUBMED_SOURCE_NAME
            or item.citation.source_url == PUBMED_SOURCE_URL
            or host == "pubmed.ncbi.nlm.nih.gov"
        ):
            continue

        filtered.append(item)

    return filtered


def _source_filter_conditions():
    if PUBMED_USER_FACING_ENABLED:
        return []

    return [
        not_(
            or_(
                KnowledgeSource.name == PUBMED_SOURCE_NAME,
                KnowledgeSource.source_url == PUBMED_SOURCE_URL,
                func.coalesce(
                    func.lower(KnowledgeDocument.source_url), ""
                ).like("https://pubmed.ncbi.nlm.nih.gov/%"),
            )
        )
    ]


def _make_retrieved_chunk(
    chunk,
    document,
    source,
    relevance: float,
    now: datetime,
) -> RetrievedChunk:
    metadata = getattr(document, "source_metadata", None) or {}
    published = getattr(document, "source_updated_at", None)
    retrieved_at = (
        getattr(document, "ingested_at", None)
        or getattr(document, "last_seen_at", None)
    )

    if published is not None:
        published_utc = published.replace(
            tzinfo=published.tzinfo or timezone.utc
        )
        age_days = max(0, (now - published_utc).days)
        freshness = "current" if age_days <= 730 else "historical"
        freshness_weight = 1.0 if age_days <= 730 else 0.8
    else:
        freshness = "unknown"
        freshness_weight = 1.0

    return RetrievedChunk(
        text=chunk.text,
        score=float(relevance) * freshness_weight,
        citation=Citation(
            source_id=source.id,
            source_name=source.name,
            source_url=(
                getattr(document, "source_url", None)
                or source.source_url
            ),
            source_reference=source.source_reference,
            document_id=document.id,
            document_title=document.title,
            document_version=document.version,
            chunk_id=chunk.id,
            publisher=getattr(source, "publisher", None),
            publication_date=(
                metadata.get("publication_date")
                or (published.isoformat() if published else None)
            ),
            retrieved_at=(
                metadata.get("retrieved_at")
                or (retrieved_at.isoformat() if retrieved_at else None)
            ),
            trust_classification="approved_source_registry",
            freshness=freshness,
        ),
    )


async def retrieve_chunks(
    db: AsyncSession,
    query: str,
    *,
    limit: int | None = None,
) -> list[RetrievedChunk]:

    limit = settings.AI_RAG_TOP_K if limit is None else limit

    if not query.strip() or len(query) > 4000 or not 1 <= limit <= 20:
        return []

    now = datetime.now(timezone.utc)
    source_filters = _source_filter_conditions()

    # 1. Keyword retrieval
    keyword_results = []

    expanded = expand_medical_query(query)

    if expanded:
        tsquery = func.websearch_to_tsquery("simple", expanded)
        text_vector = func.to_tsvector("simple", KnowledgeChunk.text)
        keyword_score = func.ts_rank_cd(text_vector, tsquery)

        keyword_statement = (
            select(
                KnowledgeChunk,
                KnowledgeDocument,
                KnowledgeSource,
                keyword_score.label("relevance"),
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeDocument.source_id,
            )
            .where(
                text_vector.op("@@")(tsquery),
                KnowledgeSource.review_status == "approved",
                KnowledgeDocument.status == "published",
                *source_filters,
            )
            .order_by(
                keyword_score.desc(),
                KnowledgeDocument.id,
                KnowledgeChunk.chunk_index,
            )
            .limit(min(80, limit * 4))
        )

        result = await db.execute(keyword_statement)

        keyword_results = [
            (chunk, document, source, float(relevance))
            for chunk, document, source, relevance in result.all()
        ]

    # 2. Semantic retrieval
    semantic_results = []

    try:
        provider = get_embedding_provider()
        query_vectors = await provider.embed([query])

        if query_vectors and query_vectors[0]:
            query_vector = query_vectors[0]

            semantic_statement = (
                select(KnowledgeChunk, KnowledgeDocument, KnowledgeSource)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeDocument.source_id,
                )
                .where(
                    KnowledgeChunk.embedding.is_not(None),
                    KnowledgeChunk.embedding_provider == provider.provider_name,
                    KnowledgeChunk.embedding_model == provider.model_name,
                    KnowledgeSource.review_status == "approved",
                    KnowledgeDocument.status == "published",
                    *source_filters,
                )
                .limit(5000)
            )

            result = await db.execute(semantic_statement)

            scored = []

            for chunk, document, source in result.all():
                similarity = _cosine_similarity(
                    query_vector,
                    chunk.embedding,
                )

                if similarity > 0:
                    scored.append(
                        (chunk, document, source, similarity)
                    )

            scored.sort(key=lambda item: item[3], reverse=True)
            semantic_results = scored[: min(80, limit * 4)]

    except Exception:
        # Semantic search failure must not disable keyword retrieval.
        semantic_results = []

    # 3. Reciprocal Rank Fusion
    # RRF avoids mixing incomparable raw keyword and cosine scores.
    fused = {}

    for ranking in (keyword_results, semantic_results):
        for rank, item in enumerate(ranking, start=1):
            chunk, document, source, raw_score = item
            key = chunk.id

            if key not in fused:
                fused[key] = {
                    "chunk": chunk,
                    "document": document,
                    "source": source,
                    "score": 0.0,
                }

            fused[key]["score"] += 1.0 / (60 + rank)

    candidates = []

    for item in fused.values():
        candidates.append(
            _make_retrieved_chunk(
                item["chunk"],
                item["document"],
                item["source"],
                item["score"],
                now,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)

    # 4. Final safety filters, deduplication and limit
    output = []
    retained_text = []

    safe_candidates = filter_user_facing_sources(
        sanitize_retrieved_chunks(candidates)
    )

    for item in safe_candidates:
        if _is_redundant(item.text, retained_text):
            continue

        output.append(item)
        retained_text.append(item.text)

        if len(output) >= limit:
            break

    return output
