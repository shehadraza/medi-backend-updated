import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.models.ai import KnowledgeDocument, KnowledgeSyncState
from app.modules.ai import knowledge_sync
from app.modules.ai.rag.retrieval import _is_redundant, expand_medical_query, retrieve_chunks
from app.modules.ai.rag.evidence import potential_disagreement_pairs
from app.modules.ai.rag.citations import Citation
from app.modules.ai.service import _reference_messages, _system_prompt
from app.modules.ai.rag.retrieval import RetrievedChunk
from app.modules.ai.source_adapters import SOURCE_ADAPTERS
from app.modules.ai.source_policy import PUBMED_ACQUISITION_ENABLED, PUBMED_USER_FACING_ENABLED
from app.modules.ai.claim_validation import EvidencePassage, catalog_passages, validate_claims


def test_source_registry_contains_only_documented_adapters():
    by_key = {adapter.key: adapter for adapter in SOURCE_ADAPTERS}
    assert set(by_key) == {"medlineplus", "pubmed"}
    assert "webservices" in by_key["medlineplus"].policy_url
    assert "ncbi.nlm.nih.gov" in by_key["pubmed"].policy_url
    assert by_key["pubmed"].acquisition_enabled is False
    assert by_key["pubmed"].user_facing_enabled is False
    assert by_key["medlineplus"].user_facing_enabled is True
    assert PUBMED_ACQUISITION_ENABLED is False
    assert PUBMED_USER_FACING_ENABLED is False


@pytest.mark.asyncio
async def test_pubmed_sync_is_default_denied_without_database_or_network():
    class ForbiddenDB:
        async def execute(self, *args, **kwargs):
            raise AssertionError("disabled PubMed must not access storage")

    result = await knowledge_sync.sync_pubmed(ForbiddenDB())
    assert result["disabled"] == 1
    assert result["created"] == 0


def test_pubmed_parser_rejects_xml_entities_and_preserves_provenance_fields():
    attack = b'<!DOCTYPE x [<!ENTITY e "expanded">]><PubmedArticleSet>&e;</PubmedArticleSet>'
    with pytest.raises(ValueError, match="declarations_forbidden"):
        knowledge_sync._parse_pubmed_xml(attack)
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID>
      <Article><ArticleTitle>Example health article</ArticleTitle><Language>eng</Language>
      <Abstract><AbstractText>A useful abstract that describes a medical topic with sufficient content for validation.</AbstractText></Abstract>
      <Journal><JournalIssue><PubDate><Year>2025</Year><Month>Feb</Month><Day>3</Day></PubDate></JournalIssue></Journal>
      </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    record, = knowledge_sync._parse_pubmed_xml(xml)
    assert record["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert record["external_id"] == "12345"
    assert record["publication_date"] == "2025-Feb-3"
    assert record["updated"] == "2025-02-03"
    assert record["source_type"] == "research_abstract"


@pytest.mark.asyncio
async def test_medlineplus_fetch_uses_official_search_service_and_validates_result_urls():
    seen = []
    xml = b"""<search-results><document url="https://medlineplus.gov/healthtopic.html" title="Health topic" date="2025-01-01">
      <content name="snippet"><![CDATA[A sufficiently long health information summary for validating the official source adapter and its response parsing behavior.]]></content>
      </document></search-results>"""

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, content=xml)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await knowledge_sync.fetch_medlineplus(client, "diabetes")
    assert len(records) == 1
    assert seen[0].url.host == "wsearch.nlm.nih.gov"
    assert seen[0].url.params["db"] == "healthTopics"
    assert seen[0].url.params["term"] == "diabetes"
    assert records[0]["url"].startswith("https://medlineplus.gov/")


@pytest.mark.asyncio
async def test_pubmed_fetch_uses_only_official_endpoints_and_bounded_results():
    seen = []

    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        return httpx.Response(200, content=b"<PubmedArticleSet/>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await knowledge_sync.fetch_pubmed(client, "diabetes[Title/Abstract]")
        with pytest.raises(ValueError, match="query_invalid"):
            await knowledge_sync.fetch_pubmed(client, "x" * 161)
    assert records == []
    assert len(seen) == 2
    assert all(request.url.host == "eutils.ncbi.nlm.nih.gov" for request in seen)
    assert all(request.url.params.get("tool") == "MEDI" for request in seen)


def test_bilingual_query_expansion_includes_cross_language_equivalents():
    expansion = expand_medical_query("মাথা ব্যথা")
    assert "headache" in expansion
    assert "মাথা ব্যথা" in expansion
    assert "মা OR" not in expansion
    assert "ডায়াবেটিস" in expand_medical_query("diabetes causes")
    assert "asthma" in expand_medical_query("হাঁপানি")
    mixed = expand_medical_query("headache মাথা ব্যথা")
    assert "headache" in mixed and "মাথা ব্যথা" in mixed
    assert "headaches" in expand_medical_query("headaches")
    assert "high blood pressure" in expand_medical_query("hypertension")
    assert "hypertension" in expand_medical_query("high blood pressure")
    assert "diabetes" in expand_medical_query("high blood sugar")


def test_duplicate_passages_are_removed_but_distinct_passages_are_retained():
    first = "Adults with asthma may use the prescribed inhaler as directed by their clinician."
    duplicate = "Adults with asthma may use the prescribed inhaler as directed by their clinician"
    distinct = "Asthma symptoms can include wheezing, coughing, and shortness of breath."
    assert _is_redundant(duplicate, [first])
    assert not _is_redundant(distinct, [first])


def test_potential_conflict_marker_is_conservative_and_not_a_clinical_verdict():
    texts = [
        "For this condition the treatment is recommended for adults.",
        "For this condition the treatment is not recommended for adults.",
        "Different subject matter is effective in selected patients.",
    ]
    assert (0, 1) in potential_disagreement_pairs(texts)
    assert (0, 2) not in potential_disagreement_pairs(texts)


def test_potential_disagreement_is_marked_as_untrusted_cue_in_prompt():
    passages = []
    for i, text in enumerate((
        "This treatment is recommended for adults with condition X.",
        "This treatment is not recommended for adults with condition X.",
    )):
        citation = Citation(
            f"source-{i}", f"Source {i}", f"https://example.org/{i}", "Official source",
            f"doc-{i}", f"Guidance {i}", 1, f"chunk-{i}",
        )
        passages.append(RetrievedChunk(text, 0.9, citation))
    messages = _reference_messages({}, passages, [])
    assert any('"potential_disagreement":true' in message for message in messages)
    assert "not proof of a clinical conflict" in _system_prompt("en", True)


def _valid_rag_citation(**overrides):
    row = {
        "source_id": "db-source-1", "source_name": "MedlinePlus Web Service",
        "source_url": "https://medlineplus.gov/topic.html", "source_reference": "Official Web Service",
        "document_id": "db-document-1", "document_title": "Headache guidance",
        "document_version": 2, "chunk_id": "db-chunk-1", "publisher": "U.S. National Library of Medicine",
        "publication_date": "2025-01-01", "retrieved_at": "2025-02-01T00:00:00+00:00",
        "trust_classification": "approved_source_registry", "freshness": "current",
    }
    row.update(overrides)
    return row


def test_claim_validator_maps_each_claim_to_only_its_supporting_passages():
    first = EvidencePassage(
        "Headache may be associated with dehydration and inadequate sleep.",
        _valid_rag_citation(chunk_id="chunk-a", document_id="doc-a"),
    )
    second = EvidencePassage(
        "A fever can occur with some infections.",
        _valid_rag_citation(chunk_id="chunk-b", document_id="doc-b", source_name="NHS"),
    )
    checked = validate_claims(
        "Headache may be associated with dehydration and inadequate sleep. A fever can occur with some infections.",
        [first, second],
    )
    assert checked.supported
    assert [claim["citation_ids"] for claim in checked.claims] == [["chunk-a"], ["chunk-b"]]
    assert {citation["chunk_id"] for citation in checked.citations} == {"chunk-a", "chunk-b"}
    assert checked.citations[0]["claim_ids"] == ["c1"]


@pytest.mark.parametrize("answer", [
    "Headache always means dehydration.",
    "Take 500 mg of ExampleMed every day.",
    "According to WHO, headache is always harmless.",
    "See https://fake.example/source [77].",
    "Source ID: fake-record-1 supports this claim.",
])
def test_unsupported_claims_and_fabricated_citation_markers_fail_closed(answer):
    evidence = EvidencePassage(
        "Headache may be associated with dehydration.",
        _valid_rag_citation(),
    )
    checked = validate_claims(answer, [evidence])
    assert not checked.supported
    assert checked.citations == []
    assert "could not verify" in checked.response


def test_claim_validator_rejects_untrusted_or_malformed_citation_provenance():
    evidence = EvidencePassage(
        "Headache may be associated with dehydration.",
        _valid_rag_citation(source_url="https://user:pass@evil.example/claim", trust_classification="pending"),
    )
    checked = validate_claims("Headache may be associated with dehydration.", [evidence])
    assert not checked.supported
    assert checked.citations == []


def test_claim_validator_does_not_attach_unrelated_passages():
    relevant = EvidencePassage(
        "Headache may be associated with dehydration.",
        _valid_rag_citation(chunk_id="relevant"),
    )
    unrelated = EvidencePassage(
        "Asthma symptoms can include wheezing and coughing.",
        _valid_rag_citation(chunk_id="unrelated", document_id="doc-unrelated"),
    )
    checked = validate_claims("Headache may be associated with dehydration.", [relevant, unrelated])
    assert checked.supported
    assert [item["chunk_id"] for item in checked.citations] == ["relevant"]


def test_verified_catalog_evidence_retains_its_catalog_citation():
    passages = catalog_passages([{
        "catalog_id": "catalog-1", "generic_name": "ExampleMed", "brand_name": "Example",
        "common_uses": ["documented use"], "source_name": "Regulator",
        "source_url": "https://example.gov.bd/medicine", "last_verified_at": "2025-01-01",
    }])
    checked = validate_claims("ExampleMed common uses documented use.", passages)
    assert checked.supported
    assert checked.citations[0]["citation_type"] == "medicine_catalog"
    assert checked.citations[0]["catalog_id"] == "catalog-1"


def test_document_update_rejects_untrusted_source_host():
    db = SyncDB(KnowledgeDocument(
        id="doc", source_id="source-id", title="Topic", language="en", version=1,
        content_hash="a" * 64, status="published", source_url="https://medlineplus.gov/topic.html",
        metadata_history=[],
    ))
    result = asyncio.run(knowledge_sync._apply_records(
        db, "source-id", [{
            "title": "Untrusted", "url": "https://evil.example/topic",
            "text": "medical topic content " * 10, "language": "en",
        }], datetime.now(timezone.utc),
    ))
    assert result["seen"] == 0
    assert result["rejected"] == 1
    assert db.document.status == "published"


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class RetrievalDB:
    def __init__(self, rows):
        self.rows, self.statement = rows, None
        self.statements = []

    async def execute(self, statement):
        self.statement = statement
        self.statements.append(statement)
        return Result(self.rows)


@pytest.mark.asyncio
async def test_pubmed_source_rows_are_excluded_while_medlineplus_stays_retrievable():
    now = datetime.now(timezone.utc)
    rows = []
    source_cases = (
        ("PubMed via NCBI E-utilities", "https://pubmed.ncbi.nlm.nih.gov/", "https://pubmed.ncbi.nlm.nih.gov/101/"),
        ("MedlinePlus Web Service", "https://medlineplus.gov/about/developers/webservices/", "https://medlineplus.gov/topic.html"),
        ("Renamed source", "https://other.example/source", "https://pubmed.ncbi.nlm.nih.gov/102/"),
    )
    for index, (name, source_url, document_url) in enumerate(source_cases):
        chunk = type("Chunk", (), {"id": f"chunk-{index}", "text": f"Distinct clinical evidence passage {index} about headache."})()
        document = type("Doc", (), {
            "id": f"doc-{index}", "title": f"Evidence {index}", "version": 1,
            "source_updated_at": now, "ingested_at": now,
            "source_url": document_url,
            "source_metadata": {},
        })()
        source = type("Source", (), {
            "id": f"source-{index}", "name": name, "publisher": name,
            "source_url": source_url,
            "source_reference": "policy",
        })()
        rows.append((chunk, document, source, 0.8))
    db = RetrievalDB(rows)
    found = await retrieve_chunks(db, "headache", limit=5)
    sql = "\n".join(
    str(statement.compile(dialect=postgresql.dialect()))
    for statement in db.statements
)
    assert "websearch_to_tsquery" in sql
    assert [item.citation.source_name for item in found] == ["MedlinePlus Web Service"]
    pubmed_citation = Citation(
        "pubmed-source", "PubMed via NCBI E-utilities", "https://pubmed.ncbi.nlm.nih.gov/",
        "NCBI policy", "pubmed-doc", "Research abstract", 1, "pubmed-chunk",
    )
    leaked = _reference_messages({}, [RetrievedChunk("headache evidence", 0.9, pubmed_citation)], [])
    assert leaked == []


@pytest.mark.asyncio
async def test_retrieval_query_uses_multilingual_fts_and_backend_provenance():
    chunk = type("Chunk", (), {"id": "chunk-1", "text": "Clinical evidence about headache."})()
    document = type("Doc", (), {
        "id": "doc-1", "title": "Headache guidance", "version": 2,
        "source_updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "ingested_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
        "source_metadata": {"publication_date": "2025-01-01"},
    })()
    source = type("Source", (), {
        "id": "source-1", "name": "Health authority", "publisher": "Authority",
        "source_url": "https://example.org/topic", "source_reference": "Official API",
    })()
    db = RetrievalDB([(chunk, document, source, 0.75)])
    results = await retrieve_chunks(db, "মাথা ব্যথা", limit=3)
    sql = "\n".join(
    str(statement.compile(dialect=postgresql.dialect()))
    for statement in db.statements
)
    assert "websearch_to_tsquery" in sql
    assert results[0].citation.publisher == "Authority"
    assert results[0].citation.publication_date == "2025-01-01"
    assert results[0].citation.retrieved_at == document.ingested_at.isoformat()
    assert results[0].citation.freshness == "current"


@pytest.mark.asyncio
async def test_retrieval_prefers_fresher_evidence_and_preserves_multiple_source_citations():
    now = datetime.now(timezone.utc)
    rows = []
    for i, age_days in enumerate((1500, 20)):
        chunk = type("Chunk", (), {"id": f"chunk-{i}", "text": f"Distinct evidence passage number {i}."})()
        document = type("Doc", (), {
            "id": f"doc-{i}", "title": f"Guidance {i}", "version": 3,
            "source_updated_at": now - timedelta(days=age_days),
            "ingested_at": now, "source_metadata": {"publication_date": f"202{i}-01-01"},
        })()
        source = type("Source", (), {
            "id": f"source-{i}", "name": f"Publisher {i}", "publisher": f"Publisher {i}",
            "source_url": f"https://example.org/{i}", "source_reference": "Official policy",
        })()
        rows.append((chunk, document, source, 0.5))
    results = await retrieve_chunks(RetrievalDB(rows), "headache treatment", limit=2)
    assert [item.citation.source_id for item in results] == ["source-1", "source-0"]
    assert results[0].citation.freshness == "current"
    assert results[1].citation.freshness == "historical"
    assert all(item.citation.document_version == 3 for item in results)


class SyncResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class SyncDB:
    def __init__(self, document):
        self.document = document
        self.results = [SyncResult("source-id"), SyncResult(document)]
        self.state = KnowledgeSyncState(source_id="source-id")
        self.added = []

    async def execute(self, statement):
        return self.results.pop(0) if self.results else SyncResult()

    async def get(self, model, key):
        return self.state

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_metadata_only_updates_version_once_and_repeated_sync_is_idempotent():
    record = {
        "title": "Health topic", "url": "https://medlineplus.gov/topic.html",
        "text": "validated medical topic content " * 15, "language": "en",
        "updated": "2025-01-01", "publication_date": "2025-01-01",
        "source_type": "government_health_topic",
    }
    digest = knowledge_sync.hashlib.sha256(
        knowledge_sync.normalize_text(record["text"]).encode()
    ).hexdigest()
    document = KnowledgeDocument(
        id="doc-1", source_id="source-id", title="Older title", language="en", version=1,
        content_hash=digest, status="published", source_url=record["url"],
        source_updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc), metadata_history=[],
    )
    db = SyncDB(document)
    first = await knowledge_sync._apply_records(db, "source-id", [record], datetime(2025, 2, 1, tzinfo=timezone.utc))
    assert first["metadata_updated"] == 1 and document.version == 2
    assert document.source_metadata["publication_date"] == "2025-01-01"
    assert document.metadata_history
    db.results = [SyncResult("source-id"), SyncResult(document)]
    second = await knowledge_sync._apply_records(db, "source-id", [record], datetime(2025, 2, 2, tzinfo=timezone.utc))
    assert second["unchanged"] == 1
    assert document.version == 2
