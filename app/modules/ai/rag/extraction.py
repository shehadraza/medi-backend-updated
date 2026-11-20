from pathlib import Path


class DocumentExtractionError(ValueError):
    pass


def extract_document_text(content: bytes, filename: str) -> str:
    """Extract text from UTF-8 text/Markdown or PDF without OCR guesses."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentExtractionError("Text document is not valid UTF-8.") from exc
    if suffix == ".pdf":
        try:
            import fitz
            with fitz.open(stream=content, filetype="pdf") as document:
                return "\n".join(page.get_text("text") for page in document)
        except Exception as exc:
            raise DocumentExtractionError("Unable to extract PDF text.") from exc
    raise DocumentExtractionError("Supported document types are UTF-8 text, Markdown, and PDF.")
