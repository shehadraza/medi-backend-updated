"""Conservative lexical evidence-to-claim matching for generated answers.

This is a fail-closed overlap validator, not a medical entailment model. It only
accepts a claim when one provenance-valid passage contains nearly all of its
content terms and exact quantities. Otherwise the complete generated answer is
replaced with an uncertainty response.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse


_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?|[\u0980-\u09ff]+", re.UNICODE)
_QUANTITY = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|μg|µg|g|ml|mL|tablet(?:s)?|capsule(?:s)?|%|days?)\b", re.I)
_INLINE_CITATION = re.compile(
    r"https?://|\bwww\.|(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])|"
    r"(?:\(\s*\d+\s*\))|\b(?:PMID|DOI)\s*[:#]?\s*\S+|\bsource(?:\s+id)?\s*[:#]",
    re.I,
)
_ATTRIBUTION = re.compile(r"\baccording to\s+([^,.;:]+)", re.I)
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "to",
    "of", "for", "in", "on", "at", "and", "or", "but", "with", "from", "as",
    "this", "that", "these", "those", "it", "its", "by", "has", "have", "may", "might", "can",
    "could", "often", "usually", "commonly", "include", "includes", "including",
    "cause", "causes", "caused", "help", "helps", "such", "than", "which",
    "যে", "এবং", "বা", "হয়", "হয়", "করে", "করতে", "জন্য", "এর", "একটি", "এই",
    "সেই", "থেকে", "সাথে", "মধ্যে", "হতে", "পারে", "সাধারণত",
}
_NEGATION = {"not", "no", "never", "without", "না", "নয়", "নয়", "নেই"}
_NON_FACTUAL = re.compile(
    r"^(?:hello|hi|thanks|thank you|you'?re welcome|i can help|i am here|i'm here|"
    r"how can i help|please tell me|i cannot diagnose|i can'?t diagnose|"
    r"i could not verify|i couldn't verify|i do not have reliable source evidence|"
    r"please (?:ask|consult|contact|speak with)|ask your (?:doctor|clinician|pharmacist)|"
    r"i cannot recommend changing|i can'?t recommend changing)\b",
    re.I,
)
_PRESCRIBING_ACTION = re.compile(
    r"^\s*(?:please\s+)?(?:take|use|start|stop|increase|decrease|change)\b|"
    r"^\s*(?:\u0996\u09be\u09a8|\u0996\u09c7\u09a4\u09c7|\u09a8\u09bf\u09a8|\u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0\s+\u0995\u09b0\u09c1\u09a8|\u09b6\u09c1\u09b0\u09c1\u0995\u09b0\u09c1\u09a8|\u09ac\u09a8\u09cd\u09a7\u0995\u09b0\u09c1\u09a8)\b|"
    r"\b(?:you should|you can|i recommend|start|stop|increase|decrease|change)\b.{0,70}"
    r"\b(?:take|using|use|medicine|medication|drug|dose|dosage|tablet|capsule)\b",
    re.I,
)


@dataclass(frozen=True)
class EvidencePassage:
    text: str
    citation: dict


@dataclass(frozen=True)
class ClaimValidation:
    response: str
    citations: list[dict]
    claims: list[dict]
    supported: bool


def _stem(token: str) -> str:
    value = token.casefold()
    if re.fullmatch(r"[a-z]+", value):
        if len(value) > 5 and value.endswith("ies"):
            return value[:-3] + "y"
        if len(value) > 5 and value.endswith("es"):
            return value[:-2]
        if len(value) > 4 and value.endswith("s"):
            return value[:-1]
        if len(value) > 5 and value.endswith("ed"):
            return value[:-2]
    return value


def _content_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return [
        _stem(token) for token in _TOKEN.findall(normalized)
        if token.casefold() not in _STOP and len(token) > 1
    ]


def _terms(text: str) -> set[str]:
    return set(_content_terms(text))


def _valid_citation(citation: dict) -> bool:
    if citation.get("citation_type") == "medicine_catalog":
        required = ("catalog_id", "source_name", "source_url")
        if not all(citation.get(key) for key in required):
            return False
    else:
        required = (
            "source_id", "source_name", "source_url", "document_id",
            "document_title", "document_version", "chunk_id",
        )
        if not all(citation.get(key) for key in required):
            return False
        if citation.get("trust_classification") != "approved_source_registry":
            return False
        if not isinstance(citation.get("document_version"), int) or citation["document_version"] < 1:
            return False
    try:
        parsed = urlparse(str(citation["source_url"]))
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (KeyError, TypeError, ValueError):
        return False


def _sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+|\n+", answer.strip())
    return [part.strip(" -*\t") for part in parts if part.strip(" -*\t")]


def _claim_support(claim: str, passage: EvidencePassage) -> bool:
    claim_terms = _content_terms(claim)
    if len(claim_terms) < 2:
        return False

    claim_set = set(claim_terms)
    claim_negated = bool(claim_set & _NEGATION)

    quantities = {
        re.sub(r"\s+", "", value.casefold())
        for value in _QUANTITY.findall(claim)
    }

    for source_sentence in _sentences(passage.text):
        source_terms = set(_content_terms(source_sentence))
        source_negated = bool(source_terms & _NEGATION)

        # Every claim term must occur in the same evidence sentence.
        # Additional source context and different word order are allowed.
        if not claim_set.issubset(source_terms):
            continue

        # Preserve negation and exact quantity safeguards.
        if claim_negated != source_negated:
            continue

        source_quantities = {
            re.sub(r"\s+", "", value.casefold())
            for value in _QUANTITY.findall(source_sentence)
        }

        if not quantities.issubset(source_quantities):
            continue

        return True

    return False


def validate_claims(
    answer: str,
    evidence: list[EvidencePassage],
    *,
    locale: str = "en",
) -> ClaimValidation:
    """Map each factual sentence to only passages that independently support it."""
    sentences = _sentences(answer)
    if not sentences:
        return _insufficient(locale, [])
    if _INLINE_CITATION.search(answer):
        claims = [{"claim_id": f"c{i + 1}", "text": sentence, "supported": False, "citation_ids": []}
                  for i, sentence in enumerate(sentences)]
        return _insufficient(locale, claims)
    clean_evidence = [item for item in evidence if _valid_citation(item.citation)]
    citations_by_key: dict[str, dict] = {}
    claim_results: list[dict] = []
    for sentence in sentences:
        if _NON_FACTUAL.search(sentence) and not _PRESCRIBING_ACTION.search(sentence):
            claim_results.append({
                "claim_id": f"c{len(claim_results) + 1}", "text": sentence,
                "supported": True, "citation_ids": [],
            })
            continue
        if _PRESCRIBING_ACTION.search(sentence):
            claim_results.append({
                "claim_id": f"c{len(claim_results) + 1}", "text": sentence,
                "supported": False, "citation_ids": [],
            })
            continue
        matched = []
        attribution = _ATTRIBUTION.search(sentence)
        for passage in clean_evidence:
            if attribution:
                name = attribution.group(1).strip().casefold()
                provenance = " ".join(str(passage.citation.get(key, "")) for key in ("source_name", "publisher")).casefold()
                if name not in provenance:
                    continue
            if _claim_support(sentence, passage):
                matched.append(passage)
        claim_id = f"c{len(claim_results) + 1}"
        citation_ids = []
        for passage in matched[:3]:
            key = str(passage.citation.get("chunk_id") or passage.citation.get("catalog_id"))
            citation = citations_by_key.setdefault(key, {**passage.citation, "claim_ids": []})
            if claim_id not in citation["claim_ids"]:
                citation["claim_ids"].append(claim_id)
            if key not in citation_ids:
                citation_ids.append(key)
        claim_results.append({
            "claim_id": claim_id, "text": sentence,
            "supported": bool(matched), "citation_ids": citation_ids,
        })
    if not all(item["supported"] for item in claim_results):
        return _insufficient(locale, claim_results)
    return ClaimValidation(
        response=answer,
        citations=list(citations_by_key.values()),
        claims=claim_results,
        supported=True,
    )


def _insufficient(locale: str, claims: list[dict]) -> ClaimValidation:
    response = (
        "উপলভ্য নির্ভরযোগ্য প্রমাণ দিয়ে উত্তরটির চিকিৎসা-সংক্রান্ত দাবিগুলো যাচাই করতে পারিনি। "
        "অনুগ্রহ করে যোগ্য চিকিৎসক বা ফার্মাসিস্টের সঙ্গে নিশ্চিত করুন।"
        if locale == "bn" else
        "I could not verify the medical claims in that answer against the retrieved trusted evidence. "
        "Please confirm with a qualified clinician or pharmacist."
    )
    return ClaimValidation(response=response, citations=[], claims=claims, supported=False)


def rag_passages(chunks) -> list[EvidencePassage]:
    """Create claim-validator passages only from the backend retrieval result."""
    return [
        EvidencePassage(text=item.text, citation=item.citation.as_dict())
        for item in chunks
    ]


def catalog_passages(records: list[dict]) -> list[EvidencePassage]:
    """Create separate catalog passages and citations from verified query results."""
    passages = []
    for row in records:
        fields = (
            "generic_name", "brand_name", "manufacturer", "strength", "dosage_form",
            "common_uses", "safety_information", "price_amount", "currency", "pack_size",
        )
        for key in fields:
            value = row.get(key)
            if value not in (None, ""):
                if isinstance(value, (list, tuple)):
                    value = "; ".join(str(item) for item in value if item)
                names = list(dict.fromkeys(filter(None, (row.get("generic_name"), row.get("brand_name")))))
                for name in names:
                    text = f"{name} {key.replace('_', ' ')}: {value}"
                    citation = {
                        "citation_type": "medicine_catalog",
                        "catalog_id": row.get("catalog_id"),
                        "title": " ".join(filter(None, (row.get("brand_name"), row.get("generic_name"), row.get("strength")))),
                        "source_name": row.get("source_name"),
                        "source_url": row.get("source_url"),
                        "source_reference": row.get("source_reference"),
                        "last_verified_at": row.get("last_verified_at"),
                    }
                    passages.append(EvidencePassage(text=text, citation=citation))
    return passages
