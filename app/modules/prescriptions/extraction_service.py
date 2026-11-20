
"""Conservative prescription OCR text extraction.

Only medicine lines with an explicit strength are auto-created.
Missing or ambiguous patient-specific instructions remain unset
for human review. No medicine or dosage is ever guessed.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.prescriptions.schemas import (
    ExtractedMedicine,
    PrescriptionExtractionResult,
)


# ---------------------------------------------------------
# MEDICINE RECOGNITION
# ---------------------------------------------------------

_STRENGTH = (
    r"\d+(?:\.\d+)?\s*"
    r"(?:mg|mcg|µg|g|ml|iu|%|মি?গ্রা|মি?লি)"
)

_FORMS = (
    r"tablet|tab|tabs|ট্যাবলেট|"
    r"capsule|cap|caps|ক্যাপসুল|"
    r"syrup|সিরাপ|suspension|"
    r"injection|ইনজেকশন|"
    r"drop|drops|ড্রপ|"
    r"cream|ক্রিম|ointment|মলম"
)

MEDICINE_PATTERN = re.compile(
    rf"^\s*(?:(?:rx|মেডিসিন|ঔষধ)\s*[:.-]?\s*)?"
    rf"(?:(tab(?:let)?s?|cap(?:sule)?s?|syrup|suspension|"
    rf"injection|drops?|cream|ointment|"
    rf"ট্যাবলেট|ক্যাপসুল|সিরাপ|ইনজেকশন|ড্রপ|ক্রিম|মলম)"
    rf"\.?\s+)?"
    rf"([A-Za-z\u0980-\u09FF]"
    rf"[A-Za-z0-9\u0980-\u09FF()&+./ -]{{1,79}}?)"
    rf"\s+({_STRENGTH})"
    rf"(?:\s+({_FORMS}))?"
    rf"(?:\s+.*)?$",
    re.IGNORECASE,
)


# ---------------------------------------------------------
# FREQUENCY RECOGNITION
# ---------------------------------------------------------

FREQUENCY_PATTERNS = [
    (
        re.compile(
            r"\b(once|1\s*time)\s+(daily|a\s*day)\b",
            re.I,
        ),
        "Once daily",
    ),
    (
        re.compile(
            r"\b(twice|2\s*times)\s+(daily|a\s*day)\b",
            re.I,
        ),
        "Twice daily",
    ),
    (
        re.compile(
            r"\b(thrice|3\s*times)\s+(daily|a\s*day)\b",
            re.I,
        ),
        "Three times daily",
    ),
    (
        re.compile(
            r"\b(once|1\s*time)\s+weekly\b",
            re.I,
        ),
        "Once weekly",
    ),
]

_SHORTHAND_FREQUENCY = re.compile(
    r"(?<!\d)(?:[0-9০-৯]\s*[+\-–]\s*){1,2}[0-9০-৯](?!\d)"
)


# ---------------------------------------------------------
# FOOD INSTRUCTIONS
# ---------------------------------------------------------

FOOD_PATTERNS = [
    (
        re.compile(
            r"(?:\b(?:before food|before meals)\b|"
            r"খাবারের আগে|খাওয়ার আগে|খাওয়ার আগে)",
            re.I,
        ),
        "Before food / খাবারের আগে",
    ),
    (
        re.compile(
            r"(?:\b(?:after food|after meals)\b|"
            r"খাবারের পরে|খাওয়ার পরে|খাওয়ার পরে)",
            re.I,
        ),
        "After food / খাবারের পরে",
    ),
    (
        re.compile(
            r"(?:\b(?:with food|with meals)\b|"
            r"খাবারের সাথে|খাবারের সঙ্গে)",
            re.I,
        ),
        "With food / খাবারের সাথে",
    ),
]


# ---------------------------------------------------------
# DURATION
# ---------------------------------------------------------

_DURATION_PATTERNS = [
    re.compile(
        r"\bfor\s+(\d+\s*(?:days?|weeks?|months?))\b",
        re.I,
    ),
    re.compile(
        r"\bduration\s*[:.-]\s*"
        r"(\d+\s*(?:days?|weeks?|months?))\b",
        re.I,
    ),
    re.compile(
        r"(\d+\s*(?:দিন|সপ্তাহ|মাস))"
    ),
]


# ---------------------------------------------------------
# DOSE
# ---------------------------------------------------------

def find_dose(text: str) -> str | None:
    patterns = [
        re.compile(
            r"\b(\d+(?:\.\d+)?\s*"
            r"(?:tablets?|tabs?|capsules?|caps?))\b",
            re.I,
        ),
        re.compile(
            r"\b(\d+(?:\.\d+)?\s*(?:ml|drops?))\b",
            re.I,
        ),
    ]

    for pattern in patterns:
        match = pattern.search(text)

        if match:
            return re.sub(
                r"\s+",
                " ",
                match.group(1),
            ).strip()

    return None


# ---------------------------------------------------------
# FREQUENCY
# ---------------------------------------------------------

def find_frequency(text: str) -> str | None:
    for pattern, value in FREQUENCY_PATTERNS:
        if pattern.search(text):
            return value

    shorthand = _SHORTHAND_FREQUENCY.search(text)

    if shorthand:
        return (
            f"{shorthand.group(0)} "
            "(exact prescription notation; confirm with prescriber)"
        )

    if re.search(
        r"দিনে\s*একবার|প্রতিদিন\s*একবার",
        text,
    ):
        return "Once daily / দিনে একবার"

    if re.search(
        r"দিনে\s*দুইবার|প্রতিদিন\s*দুইবার",
        text,
    ):
        return "Twice daily / দিনে দুইবার"

    if re.search(
        r"দিনে\s*তিনবার|প্রতিদিন\s*তিনবার",
        text,
    ):
        return "Three times daily / দিনে তিনবার"

    return None


# ---------------------------------------------------------
# DURATION
# ---------------------------------------------------------

def find_duration(text: str) -> str | None:
    for pattern in _DURATION_PATTERNS:
        match = pattern.search(text)

        if match:
            return match.group(1).strip()

    return None


# ---------------------------------------------------------
# FOOD INSTRUCTION
# ---------------------------------------------------------

def find_food_instruction(text: str) -> str | None:
    for pattern, value in FOOD_PATTERNS:
        if pattern.search(text):
            return value

    return None


# ---------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------

def _clean_name(value: str) -> str:
    value = re.sub(
        r"^(?:rx|tab(?:let)?s?|cap(?:sule)?s?|"
        r"মেডিসিন|ঔষধ)\s*[:.-]?\s*",
        "",
        value,
        flags=re.I,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip(" .:-")



def _normalize_form(form: str | None) -> str | None:
    if not form:
        return None

    normalized = form.lower()

    # Preserve Bangla dosage form labels.
    bangla_forms = {
        "ট্যাবলেট": "ট্যাবলেট",
        "ক্যাপসুল": "ক্যাপসুল",
        "সিরাপ": "সিরাপ",
        "ইনজেকশন": "ইনজেকশন",
        "ড্রপ": "ড্রপ",
        "ক্রিম": "ক্রিম",
        "মলম": "মলম",
    }

    for bangla, value in bangla_forms.items():
        if bangla in normalized:
            return value

    if normalized.startswith("tab"):
        return "tablet"

    if normalized.startswith("cap"):
        return "capsule"

    if normalized.startswith("syrup"):
        return "syrup"

    if normalized.startswith("suspension"):
        return "suspension"

    if normalized.startswith("injection"):
        return "injection"

    if normalized.startswith("drop"):
        return "drop"

    if normalized.startswith("cream"):
        return "cream"

    if normalized.startswith("ointment"):
        return "ointment"

    return normalized


    normalized = form.lower()

    if normalized.startswith("tab"):
        return "tablet"

    if normalized.startswith("cap"):
        return "capsule"

    if normalized.startswith("syrup"):
        return "syrup"

    if normalized.startswith("suspension"):
        return "suspension"

    if normalized.startswith("injection"):
        return "injection"

    if normalized.startswith("drop"):
        return "drop"

    if normalized.startswith("cream"):
        return "cream"

    if normalized.startswith("ointment"):
        return "ointment"

    if "ট্যাবলেট" in normalized:
        return "tablet"

    if "ক্যাপসুল" in normalized:
        return "capsule"

    if "সিরাপ" in normalized:
        return "syrup"

    if "ইনজেকশন" in normalized:
        return "injection"

    if "ড্রপ" in normalized:
        return "drop"

    if "ক্রিম" in normalized:
        return "cream"

    if "মলম" in normalized:
        return "ointment"

    return normalized


# ---------------------------------------------------------
# MEDICINE FIELD VALIDATION
# ---------------------------------------------------------

def validate_medicine_fields(
    medicine: ExtractedMedicine,
) -> list[str]:

    missing: list[str] = []

    if not medicine.medicine_name.strip():
        missing.append("medicine name")

    if not medicine.strength:
        missing.append("strength")

    if not medicine.dose:
        missing.append("dose")

    if not medicine.frequency:
        missing.append("frequency")

    if not medicine.duration:
        missing.append("duration")

    if not medicine.dosage_form:
        missing.append("dosage form")

    if medicine.frequency and (
        "confirm with prescriber" in medicine.frequency.lower()
    ):
        missing.append("frequency confirmation")

    return missing


# ---------------------------------------------------------
# PRESCRIPTION EXTRACTION
# ---------------------------------------------------------

def extract_prescription_medicines(
    prescription_id: str,
    ocr_result: dict[str, Any],
) -> PrescriptionExtractionResult:

    full_text = str(
        ocr_result.get("full_text") or ""
    )

    if not full_text.strip():
        return PrescriptionExtractionResult(
            prescription_id=prescription_id,
            extraction_status="no_medicines_detected",
            medicines=[],
            warnings=[
                "No readable OCR text was available."
            ],
            requires_user_verification=True,
        )

    lines = [
        line.strip()
        for line in full_text.splitlines()
        if line.strip()
    ]

    medicines: list[ExtractedMedicine] = []
    warnings: list[str] = []

    current: dict[str, Any] | None = None
    current_lines: list[str] = []

    def save_current() -> None:
        nonlocal current, current_lines

        if current is None:
            return

        context = " ".join(current_lines)

        current["dose"] = find_dose(context)
        current["frequency"] = find_frequency(context)
        current["duration"] = find_duration(context)
        current["food_instruction"] = find_food_instruction(context)

        current["additional_instructions"] = (
            context[:1000] or None
        )

        current["source_text"] = (
            "\n".join(current_lines)[:2000]
        )

        medicine = ExtractedMedicine(**current)

        medicines.append(medicine)

        missing_fields = validate_medicine_fields(medicine)

        if missing_fields:
            warnings.append(
                f"{medicine.medicine_name}: Please verify "
                f"{', '.join(missing_fields)} against the original "
                "prescription."
            )

        current = None
        current_lines = []

    for line in lines:
        match = MEDICINE_PATTERN.match(line)

        if match:
            save_current()

            prefix_form = match.group(1)
            name = _clean_name(match.group(2))
            strength = re.sub(
                r"\s+",
                "",
                match.group(3),
            ).lower()

            form = match.group(4) or prefix_form

            current = {
                "medicine_name": name,
                "generic_name": None,
                "brand_name": None,
                "strength": strength,
                "dosage_form": _normalize_form(form),
                "dose": None,
                "frequency": None,
                "duration": None,
                "food_instruction": None,
                "additional_instructions": None,
                "source_text": line,
                "verification_status": "needs_review",
            }

            current_lines = [line]
            continue

        if current is not None:
            current_lines.append(line)

    save_current()

    if not medicines:
        warnings.append(
            "No medicine line with a readable name and explicit "
            "strength was identified. No medicine was guessed. "
            "Please add or correct it manually."
        )

    if any(
        medicine.frequency
        and "confirm with prescriber" in medicine.frequency.lower()
        for medicine in medicines
    ):
        warnings.append(
            "Prescription shorthand was preserved exactly and "
            "has not been interpreted. Confirm its meaning with "
            "the prescriber or pharmacist."
        )

    # Preserve OCR quality warnings when supplied by OCR service.
    ocr_warnings = ocr_result.get("warnings") or []

    for warning in ocr_warnings:
        warning_text = str(warning).strip()

        if warning_text and warning_text not in warnings:
            warnings.append(warning_text)

    return PrescriptionExtractionResult(
        prescription_id=prescription_id,
        extraction_status=(
            "needs_review"
            if medicines
            else "no_medicines_detected"
        ),
        medicines=medicines,
        warnings=warnings,
        requires_user_verification=True,
    )
