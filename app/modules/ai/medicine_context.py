"""High precision retrieval of current, sourced public catalog facts."""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.medicine_catalog import MedicineCatalog
from app.modules.ai.untrusted_data import safe_untrusted_value

PRICE_QUESTION = re.compile(r"\b(price|cost|how much|bdt|taka)\b|[৳]|(দাম|মূল্য|কত টাকা)", re.IGNORECASE)
SAFETY_QUESTION = re.compile(r"\b(safe|safety|side effect|adverse|warning|risk)\b|পার্শ্বপ্রতিক্রিয়া|নিরাপদ", re.IGNORECASE)
USES_QUESTION = re.compile(r"\b(used for|uses|indication|treats)\b|কী কাজে|কোন রোগে", re.IGNORECASE)
MANUFACTURER_QUESTION = re.compile(r"\bmanufacturer|made by|company\b|কোম্পানি", re.IGNORECASE)
AVAILABILITY_QUESTION = re.compile(r"\b(available|availability|in stock)\b|পাওয়া যায়|মজুত", re.IGNORECASE)


def medicine_evidence_for_question(question: str, records: list[dict]) -> list[dict]:
    """Do not let an identity match count as evidence for absent clinical fields."""
    if PRICE_QUESTION.search(question):
        return [row for row in records if row.get("price_amount") is not None and row.get("currency")]
    if SAFETY_QUESTION.search(question):
        return [row for row in records if row.get("safety_information")]
    if USES_QUESTION.search(question):
        return [row for row in records if row.get("common_uses")]
    if re.search(r"\bmanufacturer\b|কোম্পানি", question, re.IGNORECASE):
        return [row for row in records if row.get("manufacturer")]
    return records


def deterministic_price_answer(question: str, records: list[dict], *, locale: str) -> tuple[str, list[dict]] | None:
    if not PRICE_QUESTION.search(question):
        return None
    named = [row for row in records if _name_mentioned(row.get("generic_name"), question) or _name_mentioned(row.get("brand_name"), question)]
    if len(named) != 1 or named[0].get("price_amount") is None or not named[0].get("currency"):
        text = (
            "এই ওষুধটির জন্য MEDI-তে বর্তমান যাচাইকৃত ক্যাটালগ মূল্য নেই। দাম জানতে ফার্মাসিস্ট বা অনুমোদিত বিক্রেতার সঙ্গে যোগাযোগ করুন।"
            if locale == "bn" else
            "MEDI has no current verified catalog price for the medicine you asked about. Please check with a pharmacist or authorized seller."
        )
        return text, medicine_citations(named)
    row = named[0]
    pack = row.get("pack_size") or ("রেকর্ডে উল্লেখ নেই" if locale == "bn" else "not recorded")
    verified = row.get("last_verified_at") or ("তারিখ নেই" if locale == "bn" else "date unavailable")
    title = row.get("brand_name") or row.get("generic_name")
    text = (
        f"{title}: ক্যাটালগে তালিকাভুক্ত মূল্য {row['price_amount']} {row['currency']}; প্যাক সাইজ: {pack}; সর্বশেষ যাচাই: {verified}."
        if locale == "bn" else
        f"{title}: catalog listed price {row['price_amount']} {row['currency']}; pack size: {pack}; last verified: {verified}."
    )
    return text, medicine_citations(named)


def deterministic_medicine_field_answer(question: str, records: list[dict], *, locale: str) -> tuple[str, list[dict], bool] | None:
    """Answer selected catalog-field questions directly, or state the field is unavailable."""
    field = None
    if SAFETY_QUESTION.search(question):
        field = "safety_information"
    elif USES_QUESTION.search(question):
        field = "common_uses"
    elif MANUFACTURER_QUESTION.search(question):
        field = "manufacturer"
    elif AVAILABILITY_QUESTION.search(question):
        field = "availability"
    if field is None:
        return None
    named = [row for row in records if _name_mentioned(row.get("generic_name"), question) or _name_mentioned(row.get("brand_name"), question)]
    value = named[0].get(field) if len(named) == 1 and field != "availability" else None
    if value:
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value if item)
        label = {"safety_information": "catalog safety information", "common_uses": "catalog common uses", "manufacturer": "catalog manufacturer"}[field]
        response = f"{named[0].get('generic_name')}: {label}: {value}."
        return response, medicine_citations(named), True
    label = {
        "safety_information": "verified safety information",
        "common_uses": "verified common uses",
        "manufacturer": "verified manufacturer information",
        "availability": "verified availability information",
    }[field]
    response = (
        f"এই ওষুধটির {label} MEDI-র বর্তমান যাচাইকৃত ক্যাটালগে নেই। চিকিৎসক বা ফার্মাসিস্টকে জিজ্ঞেস করুন।"
        if locale == "bn" else
        f"MEDI has no current verified catalog {label} for the medicine you asked about. Please ask a clinician or pharmacist."
    )
    return response, medicine_citations(named), False


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))


def _candidate_terms(question: str) -> list[str]:
    return list(dict.fromkeys(token for token in re.findall(r"[\w]+", question, flags=re.UNICODE) if len(token) >= 4))[:12]


def _valid_provenance(row: MedicineCatalog) -> bool:
    if not isinstance(row.source_name, str) or not row.source_name.strip() or not row.source_url:
        return False
    try:
        parsed = urlparse(row.source_url)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (TypeError, ValueError):
        return False


def _name_mentioned(name: str | None, query: str) -> bool:
    normalized_name = _normalize(name or "")
    normalized_query = f" {_normalize(query)} "
    return bool(normalized_name) and f" {normalized_name} " in normalized_query


async def find_verified_medicines(db: AsyncSession, question: str, *, limit: int = 5) -> list[dict]:
    """Use only exact whole-name mentions with verified, published, fresh provenance."""
    if not 1 <= limit <= 20:
        return []
    terms = _candidate_terms(question)
    if not terms:
        return []
    patterns = []
    for term in terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        patterns.extend((MedicineCatalog.generic_name.ilike(pattern, escape="\\"), MedicineCatalog.brand_name.ilike(pattern, escape="\\")))
    result = await db.execute(
        select(MedicineCatalog).where(
            MedicineCatalog.is_verified.is_(True),
            MedicineCatalog.is_published.is_(True),
            or_(*patterns),
        ).order_by(MedicineCatalog.last_verified_at.desc().nullslast()).limit(500)
    )
    now = datetime.now(timezone.utc)
    records = []
    for row in result.scalars().all():
        if not (_name_mentioned(row.generic_name, question) or _name_mentioned(row.brand_name, question)):
            continue
        if not _valid_provenance(row):
            continue
        verified = row.last_verified_at
        if verified is None:
            continue
        if verified.tzinfo is None:
            verified = verified.replace(tzinfo=timezone.utc)
        age_days = (now - verified).total_seconds() / 86400
        if age_days < 0 or age_days > settings.AI_MEDICINE_MAX_AGE_DAYS:
            continue
        record = safe_untrusted_value({
            "catalog_id": row.id, "generic_name": row.generic_name, "brand_name": row.brand_name,
            "manufacturer": row.manufacturer, "strength": row.strength, "dosage_form": row.dosage_form,
            "route": row.route, "common_uses": row.common_uses, "safety_information": row.safety_information,
            "price_amount": str(row.price_amount) if row.price_amount is not None else None,
            "currency": row.currency, "pack_size": row.pack_size, "source_name": row.source_name.strip(),
            "source_url": row.source_url, "source_reference": row.source_reference,
            "last_verified_at": verified.isoformat(),
        })
        if not record or not record.get("generic_name") or not record.get("source_name") or not record.get("source_url"):
            continue
        records.append(record)
        if len(records) == limit:
            break
    return records


def medicine_citations(records: list[dict]) -> list[dict]:
    return [{
        "citation_type": "medicine_catalog", "catalog_id": row["catalog_id"],
        "title": " ".join(filter(None, (row.get("brand_name"), row.get("generic_name"), row.get("strength")))),
        "source_name": row["source_name"], "source_url": row["source_url"],
        "source_reference": row.get("source_reference"), "last_verified_at": row.get("last_verified_at"),
    } for row in records]


def medicine_citations_used(records: list[dict], answer: str) -> list[dict]:
    """Cite a catalog record only when the answer names its generic or brand."""
    used = [row for row in records if _name_mentioned(row.get("generic_name"), answer) or _name_mentioned(row.get("brand_name"), answer)]
    return medicine_citations(used)
