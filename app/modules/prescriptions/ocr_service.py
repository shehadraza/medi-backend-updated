
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from statistics import mean
from typing import Any

import pymupdf
import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output


# ---------------------------------------------------------
# OCR ENGINE CONFIGURATION
# ---------------------------------------------------------

TESSERACT_PATH = Path(
    os.getenv(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
)

TESSDATA_PATH = Path(
    os.getenv(
        "TESSDATA_DIR",
        str(Path.home() / "medi-tessdata"),
    )
)

OCR_LANGUAGES = "eng+ben"

MAX_PDF_PAGES = 10
MAX_IMAGE_PIXELS = 30_000_000
OCR_TIMEOUT_SECONDS = 45

# OCR confidence thresholds
VERY_LOW_CONFIDENCE = 60
LOW_CONFIDENCE = 80

pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_PATH)

os.environ["TESSDATA_PREFIX"] = str(TESSDATA_PATH)

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# ---------------------------------------------------------
# EXCEPTIONS
# ---------------------------------------------------------

class OCRServiceError(Exception):
    """Base exception for prescription OCR errors."""


class OCRConfigurationError(OCRServiceError):
    """OCR engine or language configuration is invalid."""


class UnsupportedPrescriptionError(OCRServiceError):
    """Uploaded prescription format is unsupported."""


class OCRProcessingError(OCRServiceError):
    """OCR processing failed."""


# ---------------------------------------------------------
# CONFIGURATION VALIDATION
# ---------------------------------------------------------

def validate_ocr_configuration() -> None:
    if not TESSERACT_PATH.is_file():
        raise OCRConfigurationError(
            "Tesseract executable was not found."
        )

    if not TESSDATA_PATH.is_dir():
        raise OCRConfigurationError(
            "Tesseract language directory was not found."
        )

    required_languages = [
        TESSDATA_PATH / "eng.traineddata",
        TESSDATA_PATH / "ben.traineddata",
    ]

    for language_file in required_languages:
        if not language_file.is_file():
            raise OCRConfigurationError(
                f"Missing OCR language model: {language_file.name}"
            )


# ---------------------------------------------------------
# IMAGE PREPROCESSING
# ---------------------------------------------------------

def prepare_image(image: Image.Image) -> Image.Image:
    try:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")

        width, height = image.size

        if width <= 0 or height <= 0:
            raise UnsupportedPrescriptionError(
                "Invalid image dimensions."
            )

        if width * height > MAX_IMAGE_PIXELS:
            raise UnsupportedPrescriptionError(
                "Image dimensions are too large."
            )

        # Improve small printed text readability.
        if width < 1800:
            scale = min(2.0, 1800 / width)

            image = image.resize(
                (
                    int(width * scale),
                    int(height * scale),
                ),
                Image.Resampling.LANCZOS,
            )

        grayscale = ImageOps.grayscale(image)
        grayscale = ImageOps.autocontrast(grayscale)

        return grayscale

    except UnsupportedPrescriptionError:
        raise

    except (Image.DecompressionBombError, OSError) as exc:
        raise UnsupportedPrescriptionError(
            "Could not safely read the prescription image."
        ) from exc


# ---------------------------------------------------------
# TEXT EXTRACTION
# ---------------------------------------------------------

def extract_text_and_confidence(
    image: Image.Image,
) -> tuple[str, float | None]:

    try:
        data: dict[str, Any] = pytesseract.image_to_data(
            image,
            lang=OCR_LANGUAGES,
            config="--oem 3 --psm 6",
            output_type=Output.DICT,
            timeout=OCR_TIMEOUT_SECONDS,
        )

        lines: dict[tuple[int, int, int], list[str]] = {}
        confidence_values: list[float] = []

        for index, word in enumerate(data["text"]):
            word = str(word).strip()

            if not word:
                continue

            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )

            lines.setdefault(key, []).append(word)

            try:
                confidence = float(data["conf"][index])

                # Tesseract uses negative confidence for
                # non-word/invalid entries.
                if confidence >= 0:
                    confidence_values.append(confidence)

            except (ValueError, TypeError):
                continue

        extracted_lines = [
            " ".join(words)
            for words in lines.values()
            if words
        ]

        extracted_text = "\n".join(extracted_lines).strip()

        average_confidence = (
            round(mean(confidence_values), 2)
            if confidence_values
            else None
        )

        return extracted_text, average_confidence

    except OCRServiceError:
        raise

    except Exception as exc:
        raise OCRProcessingError(
            "Could not extract text from the prescription."
        ) from exc


# ---------------------------------------------------------
# IMAGE PRESCRIPTION OCR
# ---------------------------------------------------------

def process_image(data: bytes) -> list[dict[str, Any]]:
    try:
        with Image.open(BytesIO(data)) as source:
            image = prepare_image(source)

        try:
            text, confidence = extract_text_and_confidence(image)

            return [
                {
                    "page": 1,
                    "text": text,
                    "confidence": confidence,
                }
            ]

        finally:
            image.close()

    except UnsupportedPrescriptionError:
        raise

    except OCRServiceError:
        raise

    except Exception as exc:
        raise OCRProcessingError(
            "Image prescription processing failed."
        ) from exc


# ---------------------------------------------------------
# PDF PRESCRIPTION OCR
# ---------------------------------------------------------

def process_pdf(data: bytes) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    try:
        with pymupdf.open(
            stream=data,
            filetype="pdf",
        ) as document:

            if document.is_encrypted:
                raise UnsupportedPrescriptionError(
                    "Password-protected PDFs are not supported."
                )

            if document.page_count < 1:
                raise UnsupportedPrescriptionError(
                    "The PDF contains no pages."
                )

            if document.page_count > MAX_PDF_PAGES:
                raise UnsupportedPrescriptionError(
                    f"PDF cannot exceed {MAX_PDF_PAGES} pages."
                )

            matrix = pymupdf.Matrix(2, 2)

            for page_index in range(document.page_count):
                page = document.load_page(page_index)

                pixmap = page.get_pixmap(
                    matrix=matrix,
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )

                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )

                prepared = None

                try:
                    prepared = prepare_image(image)

                    text, confidence = extract_text_and_confidence(
                        prepared
                    )

                    results.append(
                        {
                            "page": page_index + 1,
                            "text": text,
                            "confidence": confidence,
                        }
                    )

                finally:
                    image.close()

                    if prepared is not None:
                        prepared.close()

        return results

    except UnsupportedPrescriptionError:
        raise

    except OCRServiceError:
        raise

    except Exception as exc:
        raise OCRProcessingError(
            "PDF prescription processing failed."
        ) from exc


# ---------------------------------------------------------
# OCR QUALITY WARNINGS
# ---------------------------------------------------------

def generate_ocr_warnings(
    pages: list[dict[str, Any]],
) -> list[str]:

    warnings: list[str] = []

    if not pages:
        warnings.append(
            "No prescription pages were processed. "
            "Please upload the prescription again."
        )
        return warnings

    for page in pages:
        page_number = page["page"]
        page_text = str(page["text"]).strip()
        page_confidence = page["confidence"]

        if not page_text:
            warnings.append(
                f"Page {page_number}: No readable text detected. "
                "Manual review is required."
            )
            continue

        if page_confidence is None:
            warnings.append(
                f"Page {page_number}: OCR confidence unavailable. "
                "Please review all extracted information manually."
            )

        elif page_confidence < VERY_LOW_CONFIDENCE:
            warnings.append(
                f"Page {page_number}: Very low OCR confidence "
                f"({page_confidence}%). Carefully verify all "
                "medicine names, strengths and instructions."
            )

        elif page_confidence < LOW_CONFIDENCE:
            warnings.append(
                f"Page {page_number}: Low OCR confidence "
                f"({page_confidence}%). Manual review is strongly recommended."
            )

    if not any(str(page["text"]).strip() for page in pages):
        warnings.append(
            "No readable prescription text was extracted. "
            "Please upload a clearer image or PDF."
        )

    return warnings


# ---------------------------------------------------------
# PUBLIC SERVICE FUNCTION
# ---------------------------------------------------------

def process_prescription_ocr(
    file_data: bytes,
    file_type: str,
) -> dict[str, Any]:

    if not file_data:
        raise UnsupportedPrescriptionError(
            "Prescription file is empty."
        )

    validate_ocr_configuration()

    normalized_type = file_type.lower().strip()

    if normalized_type == "application/pdf":
        pages = process_pdf(file_data)

    elif normalized_type in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        pages = process_image(file_data)

    else:
        raise UnsupportedPrescriptionError(
            "Only JPEG, PNG, WebP and PDF are supported."
        )

    full_text = "\n\n".join(
        f"Page {page['page']}\n{page['text']}"
        for page in pages
    ).strip()

    confidence_values = [
        page["confidence"]
        for page in pages
        if page["confidence"] is not None
    ]

    average_confidence = (
        round(mean(confidence_values), 2)
        if confidence_values
        else None
    )

    warnings = generate_ocr_warnings(pages)

    return {
        "engine": "Tesseract",
        "engine_version": str(
            pytesseract.get_tesseract_version()
        ),
        "languages": ["eng", "ben"],
        "page_count": len(pages),
        "pages": pages,
        "full_text": full_text,
        "average_confidence": average_confidence,
        "warnings": warnings,
        "requires_user_verification": True,
    }
