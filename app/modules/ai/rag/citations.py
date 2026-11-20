from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Citation:
    source_id: str
    source_name: str
    source_url: str | None
    source_reference: str | None
    document_id: str
    document_title: str
    document_version: int
    chunk_id: str
    publisher: str | None = None
    publication_date: str | None = None
    retrieved_at: str | None = None
    trust_classification: str = "approved_source"
    freshness: str = "unknown"

    def as_dict(self) -> dict:
        return asdict(self)
